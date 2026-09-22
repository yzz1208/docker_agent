import httpx
import pytest

from docker_agent.rag.llm import ModelResponseError, OpenAICompatibleChatClient


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
