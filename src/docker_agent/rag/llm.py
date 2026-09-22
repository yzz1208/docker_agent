from __future__ import annotations

from typing import Any, Protocol

import httpx


class ChatModel(Protocol):
    def complete(self, *, system_prompt: str, user_prompt: str) -> str: ...


class ModelResponseError(RuntimeError):
    """Raised when a chat endpoint returns an unexpected payload."""


class OpenAICompatibleChatClient:
    """Minimal client for OpenAI-compatible /chat/completions endpoints."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str = "",
        timeout_seconds: float = 60.0,
        temperature: float = 0.1,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model.strip()
        self.base_url = base_url.strip()
        self.api_key = api_key.strip()
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self._client = client

        if not self.model:
            raise ValueError("model must not be empty")
        if not self.base_url:
            raise ValueError("base_url must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    @property
    def endpoint(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        if not system_prompt.strip():
            raise ValueError("system_prompt must not be empty")
        if not user_prompt.strip():
            raise ValueError("user_prompt must not be empty")

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
        }

        if self._client is not None:
            response = self._client.post(self.endpoint, headers=headers, json=payload)
        else:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(self.endpoint, headers=headers, json=payload)

        response.raise_for_status()
        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelResponseError(
                "Model response does not contain choices[0].message.content"
            ) from exc

        if not isinstance(content, str) or not content.strip():
            raise ModelResponseError("Model returned an empty message")
        return content.strip()
