from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

import httpx

from docker_agent.observability import (
    emit_public_text_delta,
    public_text_stream_available,
)


class ChatModel(Protocol):
    def complete(self, *, system_prompt: str, user_prompt: str) -> str: ...


class StreamingChatModel(ChatModel, Protocol):
    def stream_complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> Iterator[str]: ...


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

        payload = self._build_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

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

    def stream_complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> Iterator[str]:
        """Yield public answer deltas from an OpenAI-compatible stream."""

        if not system_prompt.strip():
            raise ValueError("system_prompt must not be empty")
        if not user_prompt.strip():
            raise ValueError("user_prompt must not be empty")

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = self._build_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        payload["stream"] = True

        attempts = self.max_retries + 1
        for attempt in range(attempts):
            emitted = False
            try:
                with self._stream_once(
                    headers=headers,
                    payload=payload,
                ) as response:
                    response.raise_for_status()
                    content_type = response.headers.get(
                        "content-type",
                        "",
                    )
                    if "text/event-stream" not in content_type:
                        response.read()
                        content = _message_content(response.json())
                        emitted = True
                        yield content
                        return

                    for line in response.iter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[len("data:") :].strip()
                        if not data:
                            continue
                        if data == "[DONE]":
                            return
                        try:
                            event = json.loads(data)
                            delta = event["choices"][0]["delta"].get(
                                "content"
                            )
                        except (
                            json.JSONDecodeError,
                            KeyError,
                            IndexError,
                            TypeError,
                            AttributeError,
                        ) as exc:
                            raise ModelResponseError(
                                "Streaming model response is malformed"
                            ) from exc
                        if isinstance(delta, str) and delta:
                            emitted = True
                            yield delta
                    if emitted:
                        return
                    raise ModelResponseError(
                        "Streaming model returned no public text"
                    )
            except httpx.HTTPStatusError as exc:
                if emitted:
                    raise ModelRequestError(
                        "Streaming model request failed after output began"
                    ) from exc
                if not _is_retryable_status(exc.response.status_code):
                    raise ModelRequestError(
                        "Model request failed with HTTP "
                        f"{exc.response.status_code}: {exc}"
                    ) from exc
                last_error: Exception = exc
            except httpx.TransportError as exc:
                if emitted:
                    raise ModelRequestError(
                        "Streaming model transport failed after output began"
                    ) from exc
                last_error = exc

            if attempt + 1 < attempts:
                delay = self.retry_backoff_seconds * (2**attempt)
                if delay > 0:
                    time.sleep(delay)
                continue
            raise ModelRequestError(
                f"Streaming model request failed after {attempts} attempts: "
                f"{last_error}"
            ) from last_error

    def _build_payload(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
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
        return payload

    @contextmanager
    def _stream_once(
        self,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> Iterator[httpx.Response]:
        if self._client is not None:
            with self._client.stream(
                "POST",
                self.endpoint,
                headers=headers,
                json=payload,
            ) as response:
                yield response
            return

        with (
            httpx.Client(timeout=self.timeout_seconds) as client,
            client.stream(
                "POST",
                self.endpoint,
                headers=headers,
                json=payload,
            ) as response,
        ):
            yield response

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


def _message_content(data: object) -> str:
    try:
        content = data["choices"][0]["message"]["content"]  # type: ignore[index]
    except (KeyError, IndexError, TypeError) as exc:
        raise ModelResponseError(
            "Model response does not contain choices[0].message.content"
        ) from exc
    if not isinstance(content, str) or not content.strip():
        raise ModelResponseError("Model returned an empty message")
    return content


def complete_public_response(
    model: ChatModel,
    *,
    system_prompt: str,
    user_prompt: str,
) -> str:
    """Stream only explicitly public model output when a sink is active."""

    stream_complete = getattr(model, "stream_complete", None)
    if public_text_stream_available() and callable(stream_complete):
        chunks: list[str] = []
        for delta in stream_complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        ):
            if not delta:
                continue
            chunks.append(delta)
            emit_public_text_delta(delta)
        answer = "".join(chunks).strip()
        if not answer:
            raise ModelResponseError("Model returned an empty message")
        return answer

    return model.complete(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )


def _is_retryable_status(status_code: int) -> bool:
    return status_code in {408, 429} or 500 <= status_code <= 599
