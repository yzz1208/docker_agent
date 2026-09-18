import httpx
import pytest

from docker_agent.rag.llm import (
    ModelRequestError,
    ModelResponseError,
    OpenAICompatibleChatClient,
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
            client=http_client,
        )
        answer = client.complete(system_prompt="system", user_prompt="user")

    assert answer == "Grounded answer [1]"
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["authorization"] == "Bearer secret"
    assert '"model":"test-model"' in str(captured["body"])


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
