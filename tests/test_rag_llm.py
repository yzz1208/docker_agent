import httpx
import pytest

from docker_agent.observability import public_text_context
from docker_agent.rag.llm import (
    ModelRequestError,
    ModelResponseError,
    OpenAICompatibleChatClient,
    complete_public_response,
)


def test_openai_compatible_client_sends_chat_completion_request() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Grounded answer [1]"}}]},
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as http_client:
        client = OpenAICompatibleChatClient(
            model="test-model",
            base_url="https://example.test/v1",
            api_key="secret",
            max_tokens=1536,
            client=http_client,
        )
        answer = client.complete(system_prompt="system", user_prompt="user")

    assert answer == "Grounded answer [1]"
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["authorization"] == "Bearer secret"
    assert '"model":"test-model"' in str(captured["body"])
    assert '"max_tokens":1536' in str(captured["body"])


def test_openai_compatible_client_rejects_malformed_response() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"choices": []}))
    with httpx.Client(transport=transport) as http_client:
        client = OpenAICompatibleChatClient(
            model="test-model",
            base_url="https://example.test/v1",
            client=http_client,
        )
        with pytest.raises(ModelResponseError, match="choices"):
            client.complete(system_prompt="system", user_prompt="user")


def test_openai_compatible_client_retries_transient_connect_error() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("temporary TLS failure", request=request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Recovered"}}]},
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as http_client:
        client = OpenAICompatibleChatClient(
            model="test-model",
            base_url="https://example.test/v1",
            client=http_client,
            max_retries=1,
            retry_backoff_seconds=0,
        )
        answer = client.complete(system_prompt="system", user_prompt="user")

    assert calls == 2
    assert answer == "Recovered"


def test_openai_compatible_client_raises_after_retry_exhaustion() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("still unavailable", request=request)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as http_client:
        client = OpenAICompatibleChatClient(
            model="test-model",
            base_url="https://example.test/v1",
            client=http_client,
            max_retries=1,
            retry_backoff_seconds=0,
        )
        with pytest.raises(ModelRequestError, match="after 2 attempts"):
            client.complete(system_prompt="system", user_prompt="user")

    assert calls == 2



def test_openai_compatible_client_streams_chat_completion_deltas() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
                'data: {"choices":[{"delta":{"content":" world"}}]}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as http_client:
        client = OpenAICompatibleChatClient(
            model="test-model",
            base_url="https://example.test/v1",
            client=http_client,
        )

        assert list(
            client.stream_complete(
                system_prompt="system",
                user_prompt="user",
            )
        ) == ["Hello", " world"]


def test_public_response_streams_only_when_context_is_active() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        if '"stream":true' in body:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=(
                    'data: {"choices":[{"delta":{"content":"A"}}]}\n\n'
                    'data: {"choices":[{"delta":{"content":"B"}}]}\n\n'
                    "data: [DONE]\n\n"
                ),
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "AB"}}]},
        )

    deltas: list[str] = []
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as http_client:
        client = OpenAICompatibleChatClient(
            model="test-model",
            base_url="https://example.test/v1",
            client=http_client,
        )
        with public_text_context(deltas.append):
            answer = complete_public_response(
                client,
                system_prompt="system",
                user_prompt="user",
            )

    assert answer == "AB"
    assert deltas == ["A", "B"]
