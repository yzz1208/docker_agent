from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from docker_agent.persistence.agent_config import AgentConfigurationRecord


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
