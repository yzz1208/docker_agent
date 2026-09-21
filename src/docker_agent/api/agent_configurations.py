from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from docker_agent.agent.configuration import (
    EffectiveDockerSupportConfiguration,
)
from docker_agent.agent.configuration_schema import (
    ConfigurationGroupDescriptor,
)
from docker_agent.agent.registry import AgentDescriptor
from docker_agent.config import Settings
from docker_agent.persistence.agent_config import AgentConfigurationRecord

ConfigurationScalar = str | int | float | bool | None
ConfigurationSource = Literal["persisted", "environment", "default"]


class AgentConfigurationCreateRequest(BaseModel):
    agent_type: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    model_settings: dict[str, object] = Field(default_factory=dict)
    retrieval_settings: dict[str, object] = Field(default_factory=dict)
    runtime_settings: dict[str, object] = Field(default_factory=dict)


class AgentConfigurationUpdateRequest(BaseModel):
    display_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
    )
    enabled: bool | None = None
    model_settings: dict[str, object] | None = None
    retrieval_settings: dict[str, object] | None = None
    runtime_settings: dict[str, object] | None = None


class AgentConfigurationResponse(BaseModel):
    agent_type: str
    display_name: str
    enabled: bool
    model_settings: dict[str, object] = Field(default_factory=dict)
    retrieval_settings: dict[str, object] = Field(default_factory=dict)
    runtime_settings: dict[str, object] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class EffectiveConfigurationFieldResponse(BaseModel):
    persisted_value: ConfigurationScalar = None
    base_value: ConfigurationScalar = None
    effective_value: ConfigurationScalar = None
    source: ConfigurationSource
    editable: bool
    secure: bool
    configured: bool


class EffectiveAgentConfigurationResponse(BaseModel):
    agent_type: str
    display_name: str
    enabled: bool
    persisted: bool
    configuration_updated_at: datetime | None
    model_settings: dict[str, EffectiveConfigurationFieldResponse]
    retrieval_settings: dict[str, EffectiveConfigurationFieldResponse]
    runtime_settings: dict[str, EffectiveConfigurationFieldResponse]
    environment_settings: dict[str, EffectiveConfigurationFieldResponse]


_ENVIRONMENT_ONLY_FIELDS: dict[str, tuple[str, bool]] = {
    "model_provider": ("model_provider", False),
    "model_base_url": ("model_base_url", True),
    "model_api_key": ("model_api_key", True),
    "database_url": ("database_url", True),
    "embedding_model": ("embedding_model", False),
    "rerank_model": ("rerank_model", False),
    "tool_mode": ("tool_mode", False),
}


def build_agent_configuration_response(
    record: AgentConfigurationRecord,
) -> AgentConfigurationResponse:
    return AgentConfigurationResponse(
        agent_type=record.agent_type,
        display_name=record.display_name,
        enabled=record.enabled,
        model_settings=dict(record.model_settings),
        retrieval_settings=dict(record.retrieval_settings),
        runtime_settings=dict(record.runtime_settings),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def build_effective_agent_configuration_response(
    *,
    base: Settings,
    effective: EffectiveDockerSupportConfiguration,
    record: AgentConfigurationRecord | None,
    descriptor: AgentDescriptor,
) -> EffectiveAgentConfigurationResponse:
    persisted_groups = {
        "model_settings": (
            record.model_settings if record is not None else {}
        ),
        "retrieval_settings": (
            record.retrieval_settings if record is not None else {}
        ),
        "runtime_settings": (
            record.runtime_settings if record is not None else {}
        ),
    }
    groups = {
        group.key: _build_preference_group(
            base=base,
            effective=effective.settings,
            persisted=persisted_groups[group.key],
            group=group,
        )
        for group in descriptor.configuration_schema
    }

    return EffectiveAgentConfigurationResponse(
        agent_type=effective.agent_type,
        display_name=effective.display_name,
        enabled=effective.enabled,
        persisted=effective.persisted,
        configuration_updated_at=effective.configuration_updated_at,
        model_settings=groups.get("model_settings", {}),
        retrieval_settings=groups.get("retrieval_settings", {}),
        runtime_settings=groups.get("runtime_settings", {}),
        environment_settings=_build_environment_group(base),
    )


def _build_preference_group(
    *,
    base: Settings,
    effective: Settings,
    persisted: dict[str, object],
    group: ConfigurationGroupDescriptor,
) -> dict[str, EffectiveConfigurationFieldResponse]:
    response: dict[str, EffectiveConfigurationFieldResponse] = {}
    for field in group.fields:
        base_value = getattr(base, field.settings_name)
        effective_value = getattr(effective, field.settings_name)
        is_persisted = field.key in persisted
        response[field.key] = EffectiveConfigurationFieldResponse(
            persisted_value=(
                persisted[field.key]
                if is_persisted
                else None
            ),
            base_value=base_value,
            effective_value=effective_value,
            source=(
                "persisted"
                if is_persisted
                else _base_source(base, field.settings_name)
            ),
            editable=True,
            secure=False,
            configured=_is_configured(effective_value),
        )
    return response


def _build_environment_group(
    base: Settings,
) -> dict[str, EffectiveConfigurationFieldResponse]:
    response: dict[str, EffectiveConfigurationFieldResponse] = {}
    for field_name, (settings_name, secure) in _ENVIRONMENT_ONLY_FIELDS.items():
        value = getattr(base, settings_name)
        visible_value = None if secure else value
        response[field_name] = EffectiveConfigurationFieldResponse(
            persisted_value=None,
            base_value=visible_value,
            effective_value=visible_value,
            source=_base_source(base, settings_name),
            editable=False,
            secure=secure,
            configured=_is_configured(value),
        )
    return response


def _base_source(
    settings: Settings,
    field_name: str,
) -> Literal["environment", "default"]:
    if field_name in settings.model_fields_set:
        return "environment"
    return "default"


def _is_configured(value: object) -> bool:
    return value is not None and value != ""
