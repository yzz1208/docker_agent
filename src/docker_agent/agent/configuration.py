from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from docker_agent.agent.configuration_schema import (
    ConfigurationSchemaError,
    resolve_settings_from_schema,
)
from docker_agent.agent.registry import DOCKER_SUPPORT_DESCRIPTOR
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


def resolve_docker_support_configuration(
    base: Settings,
    record: AgentConfigurationRecord | None = None,
) -> EffectiveDockerSupportConfiguration:
    """Merge descriptor-owned product preferences over secure environment settings."""

    if record is None:
        return EffectiveDockerSupportConfiguration(
            agent_type=DOCKER_SUPPORT_DESCRIPTOR.agent_type,
            display_name=DOCKER_SUPPORT_DESCRIPTOR.display_name,
            enabled=DOCKER_SUPPORT_DESCRIPTOR.default_enabled,
            settings=base.model_copy(deep=True),
            persisted=False,
            configuration_updated_at=None,
        )

    if record.agent_type != DOCKER_SUPPORT_DESCRIPTOR.agent_type:
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
    """Validate Docker Support preferences through descriptor schema metadata."""

    try:
        return resolve_settings_from_schema(
            base,
            schema=DOCKER_SUPPORT_DESCRIPTOR.configuration_schema,
            rules=DOCKER_SUPPORT_DESCRIPTOR.configuration_rules,
            model_settings=model_settings,
            retrieval_settings=retrieval_settings,
            runtime_settings=runtime_settings,
        )
    except ConfigurationSchemaError as exc:
        raise AgentConfigurationResolutionError(str(exc)) from exc


def require_enabled(
    config: EffectiveDockerSupportConfiguration,
) -> EffectiveDockerSupportConfiguration:
    if not config.enabled:
        raise AgentDisabledError(
            f"Agent type {config.agent_type!r} is disabled"
        )
    return config
