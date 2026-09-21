from __future__ import annotations

from pydantic import BaseModel, Field

from docker_agent.agent.registry import AgentDescriptor


class AgentDescriptorResponse(BaseModel):
    agent_type: str
    display_name: str
    description: str
    capabilities: list[str] = Field(default_factory=list)
    knowledge_sources: list[str] = Field(default_factory=list)
    toolsets: list[str] = Field(default_factory=list)
    worker_roles: list[str] = Field(default_factory=list)
    configuration_groups: list[str] = Field(default_factory=list)
    default_enabled: bool


def build_agent_descriptor_response(
    descriptor: AgentDescriptor,
) -> AgentDescriptorResponse:
    return AgentDescriptorResponse(
        agent_type=descriptor.agent_type,
        display_name=descriptor.display_name,
        description=descriptor.description,
        capabilities=list(descriptor.capabilities),
        knowledge_sources=list(descriptor.knowledge_sources),
        toolsets=list(descriptor.toolsets),
        worker_roles=list(descriptor.worker_roles),
        configuration_groups=list(
            descriptor.configuration_groups
        ),
        default_enabled=descriptor.default_enabled,
    )
