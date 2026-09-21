from __future__ import annotations

import time
from typing import Any, Protocol

import httpx


class ChatModel(Protocol):
    def complete(self, *, system_prompt: str, user_prompt: str) -> str: ...


class ModelResponseError(RuntimeError):
    """Raised when a chat endpoint returns an unexpected payload."""


class ModelRequestError(RuntimeError):
    """Raised when a chat request still fails after transient retries."""


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
        max_tokens: int | None = None,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model.strip()
        self.base_url = base_url.strip()
        self.api_key = api_key.strip()
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self._client = client

        if not self.model:
            raise ValueError("model must not be empty")
        if not self.base_url:
            raise ValueError("base_url must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_tokens is not None and max_tokens <= 0:
            raise ValueError("max_tokens must be positive when configured")
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must not be negative")

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
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens

        response = self._post_with_retry(headers=headers, payload=payload)
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

    def _post_with_retry(
        self,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> httpx.Response:
        attempts = self.max_retries + 1
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                response = self._post_once(headers=headers, payload=payload)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if not _is_retryable_status(exc.response.status_code):
                    raise ModelRequestError(
                        "Model request failed with HTTP "
                        f"{exc.response.status_code}: {exc}"
                    ) from exc
            except httpx.TransportError as exc:
                last_error = exc

            if attempt + 1 < attempts:
                delay = self.retry_backoff_seconds * (2**attempt)
                if delay > 0:
                    time.sleep(delay)

        assert last_error is not None
        raise ModelRequestError(
            f"Model request failed after {attempts} attempts: {last_error}"
        ) from last_error

    def _post_once(
        self,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> httpx.Response:
        if self._client is not None:
            return self._client.post(self.endpoint, headers=headers, json=payload)

        with httpx.Client(timeout=self.timeout_seconds) as client:
            return client.post(self.endpoint, headers=headers, json=payload)


def _is_retryable_status(status_code: int) -> bool:
    return status_code in {408, 429} or 500 <= status_code <= 599
