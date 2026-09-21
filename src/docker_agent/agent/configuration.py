from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from numbers import Real

from docker_agent.config import Settings
from docker_agent.persistence.agent_config import AgentConfigurationRecord


class AgentConfigurationResolutionError(ValueError):
    """Raised when persisted preferences cannot form a valid runtime config."""


class AgentDisabledError(RuntimeError):
    """Raised when a persisted agent configuration disables the agent."""


@dataclass(frozen=True, slots=True)
class EffectiveDockerSupportConfiguration:
    """Resolved Docker Support settings with secure environment values preserved."""

    agent_type: str
    display_name: str
    enabled: bool
    settings: Settings
    persisted: bool
    configuration_updated_at: datetime | None


DOCKER_SUPPORT_MODEL_PREFERENCE_FIELDS = {
    "model_name": "model_name",
    "temperature": "model_temperature",
    "max_tokens": "model_max_tokens",
    "timeout_seconds": "model_timeout_seconds",
    "max_retries": "model_max_retries",
    "retry_backoff_seconds": "model_retry_backoff_seconds",
}
DOCKER_SUPPORT_RETRIEVAL_PREFERENCE_FIELDS = {
    "top_k": "retrieval_candidate_k",
    "rrf_k": "retrieval_rrf_k",
    "dense_weight": "retrieval_dense_weight",
    "keyword_weight": "retrieval_keyword_weight",
    "rerank_top_k": "rerank_top_k",
    "context_max_chars": "rag_context_max_chars",
}
DOCKER_SUPPORT_RUNTIME_PREFERENCE_FIELDS = {
    "max_steps": "dynamic_runtime_max_steps",
    "tool_timeout_seconds": "docker_tool_timeout_seconds",
    "logs_max_lines": "docker_logs_max_lines",
    "evidence_max_chars": "runtime_evidence_max_chars",
}

_MODEL_KEYS = set(DOCKER_SUPPORT_MODEL_PREFERENCE_FIELDS)
_RETRIEVAL_KEYS = set(DOCKER_SUPPORT_RETRIEVAL_PREFERENCE_FIELDS)
_RUNTIME_KEYS = set(DOCKER_SUPPORT_RUNTIME_PREFERENCE_FIELDS)


def resolve_docker_support_configuration(
    base: Settings,
    record: AgentConfigurationRecord | None = None,
) -> EffectiveDockerSupportConfiguration:
    """Merge allowlisted product preferences over secure environment settings."""

    if record is None:
        return EffectiveDockerSupportConfiguration(
            agent_type="docker_support",
            display_name="Docker Support",
            enabled=True,
            settings=base.model_copy(deep=True),
            persisted=False,
            configuration_updated_at=None,
        )

    if record.agent_type != "docker_support":
        raise AgentConfigurationResolutionError(
            "Docker Support resolver requires agent_type='docker_support'"
        )

    resolved_settings = resolve_docker_support_settings(
        base,
        model_settings=record.model_settings,
        retrieval_settings=record.retrieval_settings,
        runtime_settings=record.runtime_settings,
    )

    return EffectiveDockerSupportConfiguration(
        agent_type=record.agent_type,
        display_name=record.display_name,
        enabled=record.enabled,
        settings=resolved_settings,
        persisted=True,
        configuration_updated_at=record.updated_at,
    )


def resolve_docker_support_settings(
    base: Settings,
    *,
    model_settings: dict[str, object],
    retrieval_settings: dict[str, object],
    runtime_settings: dict[str, object],
) -> Settings:
    """Validate product preferences and return effective non-secret settings."""

    _reject_unknown_keys(
        model_settings,
        allowed=_MODEL_KEYS,
        group="model_settings",
    )
    _reject_unknown_keys(
        retrieval_settings,
        allowed=_RETRIEVAL_KEYS,
        group="retrieval_settings",
    )
    _reject_unknown_keys(
        runtime_settings,
        allowed=_RUNTIME_KEYS,
        group="runtime_settings",
    )

    updates: dict[str, object] = {}
    _apply_model_settings(model_settings, updates)
    _apply_retrieval_settings(retrieval_settings, updates)
    _apply_runtime_settings(runtime_settings, updates)

    dense_weight = float(
        updates.get("retrieval_dense_weight", base.retrieval_dense_weight)
    )
    keyword_weight = float(
        updates.get("retrieval_keyword_weight", base.retrieval_keyword_weight)
    )
    if dense_weight == 0 and keyword_weight == 0:
        raise AgentConfigurationResolutionError(
            "retrieval dense_weight and keyword_weight cannot both be zero"
        )

    candidate_k = int(
        updates.get("retrieval_candidate_k", base.retrieval_candidate_k)
    )
    rerank_top_k = int(
        updates.get("rerank_top_k", base.rerank_top_k)
    )
    if rerank_top_k > candidate_k:
        raise AgentConfigurationResolutionError(
            "retrieval_settings.rerank_top_k must not exceed top_k"
        )

    return base.model_copy(update=updates, deep=True)


def require_enabled(
    config: EffectiveDockerSupportConfiguration,
) -> EffectiveDockerSupportConfiguration:
    if not config.enabled:
        raise AgentDisabledError(
            f"Agent type {config.agent_type!r} is disabled"
        )
    return config


def _apply_model_settings(
    source: dict[str, object],
    updates: dict[str, object],
) -> None:
    if "model_name" in source:
        updates["model_name"] = _non_empty_string(
            source["model_name"],
            field="model_settings.model_name",
        )
    if "temperature" in source:
        updates["model_temperature"] = _bounded_float(
            source["temperature"],
            field="model_settings.temperature",
            minimum=0.0,
            maximum=2.0,
        )
    if "max_tokens" in source:
        updates["model_max_tokens"] = _positive_int(
            source["max_tokens"],
            field="model_settings.max_tokens",
        )
    if "timeout_seconds" in source:
        updates["model_timeout_seconds"] = _positive_float(
            source["timeout_seconds"],
            field="model_settings.timeout_seconds",
        )
    if "max_retries" in source:
        updates["model_max_retries"] = _non_negative_int(
            source["max_retries"],
            field="model_settings.max_retries",
        )
    if "retry_backoff_seconds" in source:
        updates["model_retry_backoff_seconds"] = _non_negative_float(
            source["retry_backoff_seconds"],
            field="model_settings.retry_backoff_seconds",
        )


def _apply_retrieval_settings(
    source: dict[str, object],
    updates: dict[str, object],
) -> None:
    if "top_k" in source:
        updates["retrieval_candidate_k"] = _positive_int(
            source["top_k"],
            field="retrieval_settings.top_k",
        )
    if "rrf_k" in source:
        updates["retrieval_rrf_k"] = _non_negative_int(
            source["rrf_k"],
            field="retrieval_settings.rrf_k",
        )
    if "dense_weight" in source:
        updates["retrieval_dense_weight"] = _non_negative_float(
            source["dense_weight"],
            field="retrieval_settings.dense_weight",
        )
    if "keyword_weight" in source:
        updates["retrieval_keyword_weight"] = _non_negative_float(
            source["keyword_weight"],
            field="retrieval_settings.keyword_weight",
        )
    if "rerank_top_k" in source:
        updates["rerank_top_k"] = _positive_int(
            source["rerank_top_k"],
            field="retrieval_settings.rerank_top_k",
        )
    if "context_max_chars" in source:
        updates["rag_context_max_chars"] = _positive_int(
            source["context_max_chars"],
            field="retrieval_settings.context_max_chars",
        )


def _apply_runtime_settings(
    source: dict[str, object],
    updates: dict[str, object],
) -> None:
    if "max_steps" in source:
        updates["dynamic_runtime_max_steps"] = _positive_int(
            source["max_steps"],
            field="runtime_settings.max_steps",
        )
    if "tool_timeout_seconds" in source:
        updates["docker_tool_timeout_seconds"] = _positive_float(
            source["tool_timeout_seconds"],
            field="runtime_settings.tool_timeout_seconds",
        )
    if "logs_max_lines" in source:
        updates["docker_logs_max_lines"] = _positive_int(
            source["logs_max_lines"],
            field="runtime_settings.logs_max_lines",
        )
    if "evidence_max_chars" in source:
        updates["runtime_evidence_max_chars"] = _positive_int(
            source["evidence_max_chars"],
            field="runtime_settings.evidence_max_chars",
        )


def _reject_unknown_keys(
    source: dict[str, object],
    *,
    allowed: set[str],
    group: str,
) -> None:
    unknown = sorted(set(source) - allowed)
    if unknown:
        labels = ", ".join(unknown)
        raise AgentConfigurationResolutionError(
            f"{group} contains unsupported fields: {labels}"
        )


def _non_empty_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentConfigurationResolutionError(
            f"{field} must be a non-empty string"
        )
    return value.strip()


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AgentConfigurationResolutionError(
            f"{field} must be a positive integer"
        )
    return value


def _non_negative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AgentConfigurationResolutionError(
            f"{field} must be a non-negative integer"
        )
    return value


def _positive_float(value: object, *, field: str) -> float:
    number = _real_number(value, field=field)
    if number <= 0:
        raise AgentConfigurationResolutionError(
            f"{field} must be positive"
        )
    return number


def _non_negative_float(value: object, *, field: str) -> float:
    number = _real_number(value, field=field)
    if number < 0:
        raise AgentConfigurationResolutionError(
            f"{field} must be non-negative"
        )
    return number


def _bounded_float(
    value: object,
    *,
    field: str,
    minimum: float,
    maximum: float,
) -> float:
    number = _real_number(value, field=field)
    if number < minimum or number > maximum:
        raise AgentConfigurationResolutionError(
            f"{field} must be between {minimum:g} and {maximum:g}"
        )
    return number


def _real_number(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise AgentConfigurationResolutionError(
            f"{field} must be a number"
        )
    return float(value)
