from __future__ import annotations

import json
import logging
import re
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from time import perf_counter
from uuid import uuid4

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_LOG_SECRET_PATTERNS = (
    re.compile(
        r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+"
    ),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+\-/=]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
)

_request_id: ContextVar[str | None] = ContextVar(
    "docker_agent_request_id",
    default=None,
)
_run_id: ContextVar[str | None] = ContextVar(
    "docker_agent_run_id",
    default=None,
)
_conversation_id: ContextVar[str | None] = ContextVar(
    "docker_agent_conversation_id",
    default=None,
)

_RUN_DURATION_BUCKETS = (
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
)
_STAGE_DURATION_BUCKETS = (
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
)
_LATENCY_STAGES = frozenset(
    {
        "decision",
        "rag_database",
        "embedding",
        "dense_retrieval",
        "keyword_retrieval",
        "fusion",
        "rerank",
        "context_build",
        "runtime",
        "answer",
        "synthesis",
        "embedding_model_warmup",
        "reranker_model_warmup",
    }
)


@dataclass(frozen=True, slots=True)
class CorrelationContext:
    request_id: str | None
    run_id: str | None
    conversation_id: str | None


class JsonLogFormatter(logging.Formatter):
    """Emit compact JSON logs with correlation identifiers."""

    def format(self, record: logging.LogRecord) -> str:
        correlation = current_correlation()
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_log_text(record.getMessage()),
        }

        for key, value in (
            (
                "request_id",
                getattr(record, "request_id", None)
                or correlation.request_id,
            ),
            (
                "run_id",
                getattr(record, "run_id", None)
                or correlation.run_id,
            ),
            (
                "conversation_id",
                getattr(record, "conversation_id", None)
                or correlation.conversation_id,
            ),
        ):
            if value is not None:
                payload[key] = value

        for field_name in (
            "http_method",
            "http_route",
            "http_status",
            "duration_ms",
            "agent_type",
            "agent_status",
            "agent_route",
            "error_type",
            "worker_count",
            "stage",
            "stage_duration_ms",
        ):
            value = getattr(record, field_name, None)
            if value is not None:
                payload[field_name] = value

        if record.exc_info:
            payload["exception"] = redact_log_text(
                self.formatException(record.exc_info)
            )

        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def redact_log_text(value: str) -> str:
    redacted = value
    for pattern in _LOG_SECRET_PATTERNS:
        redacted = pattern.sub(_redact_log_match, redacted)
    return redacted


def _redact_log_match(match: re.Match[str]) -> str:
    text = match.group(0)
    if text.lower().startswith("bearer "):
        return "Bearer [REDACTED]"
    if text.lower().startswith("sk-"):
        return "[REDACTED]"
    key = re.split(r"[:=]", text, maxsplit=1)[0].strip()
    return f"{key}=[REDACTED]"


def configure_structured_logging(level: str = "INFO") -> None:
    """Configure application logs without taking over Uvicorn/root logging."""

    logger = logging.getLogger("docker_agent")
    logger.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    logger.propagate = False


def resolve_request_id(candidate: str | None) -> str:
    if candidate is not None:
        normalized = candidate.strip()
        if _REQUEST_ID_PATTERN.fullmatch(normalized):
            return normalized
    return uuid4().hex


@contextmanager
def correlation_context(
    *,
    request_id: str | None = None,
    run_id: str | None = None,
    conversation_id: str | None = None,
) -> Iterator[CorrelationContext]:
    tokens: list[
        tuple[ContextVar[str | None], Token[str | None]]
    ] = []

    if request_id is not None:
        tokens.append((_request_id, _request_id.set(request_id)))
    if run_id is not None:
        tokens.append((_run_id, _run_id.set(run_id)))
    if conversation_id is not None:
        tokens.append(
            (
                _conversation_id,
                _conversation_id.set(conversation_id),
            )
        )

    try:
        yield current_correlation()
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)


def current_correlation() -> CorrelationContext:
    return CorrelationContext(
        request_id=_request_id.get(),
        run_id=_run_id.get(),
        conversation_id=_conversation_id.get(),
    )


class MetricsRegistry:
    """Small in-process Prometheus text registry with bounded labels."""

    def __init__(self) -> None:
        self._lock = Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._http_requests: Counter[
                tuple[str, str, str]
            ] = Counter()
            self._agent_runs: Counter[str] = Counter()
            self._agent_failures: Counter[str] = Counter()
            self._agent_routes: Counter[str] = Counter()
            self._worker_executions: Counter[str] = Counter()
            self._run_duration_count = 0
            self._run_duration_sum = 0.0
            self._run_duration_buckets: Counter[float] = Counter()
            self._stage_duration_count: Counter[str] = Counter()
            self._stage_duration_sum: Counter[str] = Counter()
            self._stage_duration_buckets: Counter[
                tuple[str, float]
            ] = Counter()

    def record_http_request(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
    ) -> None:
        key = (
            method.upper(),
            route,
            str(status_code),
        )
        with self._lock:
            self._http_requests[key] += 1

    def record_agent_run(
        self,
        *,
        status: str,
        duration_ms: int,
        route: str | None = None,
        workers: tuple[str, ...] | list[str] = (),
        error_type: str | None = None,
    ) -> None:
        duration_seconds = max(0, duration_ms) / 1000
        with self._lock:
            self._agent_runs[status] += 1
            if route:
                self._agent_routes[route] += 1
            for worker in workers:
                self._worker_executions[str(worker)] += 1
            if error_type:
                self._agent_failures[error_type] += 1

            self._run_duration_count += 1
            self._run_duration_sum += duration_seconds
            for bucket in _RUN_DURATION_BUCKETS:
                if duration_seconds <= bucket:
                    self._run_duration_buckets[bucket] += 1

    def record_stage_duration(
        self,
        *,
        stage: str,
        duration_ms: int,
    ) -> None:
        """Record one bounded internal latency stage."""

        if stage not in _LATENCY_STAGES:
            raise ValueError(f"unsupported latency stage: {stage}")
        if duration_ms < 0:
            raise ValueError("duration_ms must not be negative")

        duration_seconds = duration_ms / 1000
        with self._lock:
            self._stage_duration_count[stage] += 1
            self._stage_duration_sum[stage] += duration_seconds
            for bucket in _STAGE_DURATION_BUCKETS:
                if duration_seconds <= bucket:
                    self._stage_duration_buckets[(stage, bucket)] += 1

    def render_prometheus(self) -> str:
        with self._lock:
            http_requests = self._http_requests.copy()
            agent_runs = self._agent_runs.copy()
            agent_failures = self._agent_failures.copy()
            agent_routes = self._agent_routes.copy()
            worker_executions = self._worker_executions.copy()
            duration_count = self._run_duration_count
            duration_sum = self._run_duration_sum
            duration_buckets = self._run_duration_buckets.copy()
            stage_duration_count = self._stage_duration_count.copy()
            stage_duration_sum = self._stage_duration_sum.copy()
            stage_duration_buckets = self._stage_duration_buckets.copy()

        lines = [
            (
                "# HELP docker_agent_http_requests_total "
                "HTTP requests by method, route, and status."
            ),
            "# TYPE docker_agent_http_requests_total counter",
        ]
        for (method, route, status_code), value in sorted(
            http_requests.items()
        ):
            lines.append(
                "docker_agent_http_requests_total"
                f'{{method="{_escape_label(method)}",'
                f'route="{_escape_label(route)}",'
                f'status="{_escape_label(status_code)}"}} {value}'
            )

        lines.extend(
            [
                "# HELP docker_agent_runs_total Agent runs by final status.",
                "# TYPE docker_agent_runs_total counter",
            ]
        )
        _append_counter(lines, "docker_agent_runs_total", "status", agent_runs)

        lines.extend(
            [
                (
                    "# HELP docker_agent_run_failures_total "
                    "Failed Agent runs by error type."
                ),
                "# TYPE docker_agent_run_failures_total counter",
            ]
        )
        _append_counter(
            lines,
            "docker_agent_run_failures_total",
            "error_type",
            agent_failures,
        )

        lines.extend(
            [
                "# HELP docker_agent_run_routes_total Completed Agent runs by route.",
                "# TYPE docker_agent_run_routes_total counter",
            ]
        )
        _append_counter(
            lines,
            "docker_agent_run_routes_total",
            "route",
            agent_routes,
        )

        lines.extend(
            [
                (
                    "# HELP docker_agent_worker_executions_total "
                    "Completed worker-role executions."
                ),
                "# TYPE docker_agent_worker_executions_total counter",
            ]
        )
        _append_counter(
            lines,
            "docker_agent_worker_executions_total",
            "worker",
            worker_executions,
        )

        lines.extend(
            [
                "# HELP docker_agent_run_duration_seconds Agent run duration.",
                "# TYPE docker_agent_run_duration_seconds histogram",
            ]
        )
        for bucket in _RUN_DURATION_BUCKETS:
            lines.append(
                "docker_agent_run_duration_seconds_bucket"
                f'{{le="{bucket:g}"}} {duration_buckets[bucket]}'
            )
        lines.append(
            "docker_agent_run_duration_seconds_bucket"
            f'{{le="+Inf"}} {duration_count}'
        )
        lines.append(
            f"docker_agent_run_duration_seconds_sum {duration_sum:.6f}"
        )
        lines.append(
            f"docker_agent_run_duration_seconds_count {duration_count}"
        )

        lines.extend(
            [
                (
                    "# HELP docker_agent_stage_duration_seconds "
                    "Internal Agent stage duration by bounded stage name."
                ),
                "# TYPE docker_agent_stage_duration_seconds histogram",
            ]
        )
        for stage in sorted(stage_duration_count):
            escaped_stage = _escape_label(stage)
            for bucket in _STAGE_DURATION_BUCKETS:
                lines.append(
                    "docker_agent_stage_duration_seconds_bucket"
                    f'{{stage="{escaped_stage}",le="{bucket:g}"}} '
                    f"{stage_duration_buckets[(stage, bucket)]}"
                )
            lines.append(
                "docker_agent_stage_duration_seconds_bucket"
                f'{{stage="{escaped_stage}",le="+Inf"}} '
                f"{stage_duration_count[stage]}"
            )
            lines.append(
                "docker_agent_stage_duration_seconds_sum"
                f'{{stage="{escaped_stage}"}} '
                f"{stage_duration_sum[stage]:.6f}"
            )
            lines.append(
                "docker_agent_stage_duration_seconds_count"
                f'{{stage="{escaped_stage}"}} '
                f"{stage_duration_count[stage]}"
            )

        return "\n".join(lines) + "\n"


def _append_counter(
    lines: list[str],
    metric_name: str,
    label_name: str,
    values: Counter[str],
) -> None:
    for label_value, value in sorted(values.items()):
        lines.append(
            f'{metric_name}{{{label_name}="{_escape_label(label_value)}"}} '
            f"{value}"
        )


def _escape_label(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace('"', '\\"')
    )


@contextmanager
def stage_timer(stage: str) -> Iterator[None]:
    """Measure one bounded latency stage and emit metrics plus structured logs."""

    if stage not in _LATENCY_STAGES:
        raise ValueError(f"unsupported latency stage: {stage}")

    started = perf_counter()
    try:
        yield
    finally:
        duration_ms = max(0, round((perf_counter() - started) * 1000))
        metrics.record_stage_duration(
            stage=stage,
            duration_ms=duration_ms,
        )
        logging.getLogger("docker_agent.performance").info(
            "Agent stage completed",
            extra={
                "stage": stage,
                "stage_duration_ms": duration_ms,
            },
        )


metrics = MetricsRegistry()
