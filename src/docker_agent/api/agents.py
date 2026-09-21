from __future__ import annotations

from pydantic import BaseModel, Field

from docker_agent.agent.configuration_schema import (
    ConfigurationFieldDescriptor,
    ConfigurationGroupDescriptor,
    ConfigurationRuleDescriptor,
)
from docker_agent.agent.registry import AgentDescriptor


class ConfigurationFieldDescriptorResponse(BaseModel):
    key: str
    label: str
    description: str
    kind: str
    minimum: float | None = None
    maximum: float | None = None


class ConfigurationGroupDescriptorResponse(BaseModel):
    key: str
    label: str
    fields: list[ConfigurationFieldDescriptorResponse] = Field(
        default_factory=list
    )


class ConfigurationRuleDescriptorResponse(BaseModel):
    kind: str
    group: str
    fields: list[str] = Field(default_factory=list)
    target_field: str
    message: str


class AgentDescriptorResponse(BaseModel):
    agent_type: str
    display_name: str
    description: str
    capabilities: list[str] = Field(default_factory=list)
    knowledge_sources: list[str] = Field(default_factory=list)
    toolsets: list[str] = Field(default_factory=list)
    worker_roles: list[str] = Field(default_factory=list)
    configuration_groups: list[str] = Field(default_factory=list)
    configuration_schema: list[
        ConfigurationGroupDescriptorResponse
    ] = Field(default_factory=list)
    configuration_rules: list[
        ConfigurationRuleDescriptorResponse
    ] = Field(default_factory=list)
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
        configuration_schema=[
            _build_group_response(group)
            for group in descriptor.configuration_schema
        ],
        configuration_rules=[
            _build_rule_response(rule)
            for rule in descriptor.configuration_rules
        ],
        default_enabled=descriptor.default_enabled,
    )


def _build_group_response(
    group: ConfigurationGroupDescriptor,
) -> ConfigurationGroupDescriptorResponse:
    return ConfigurationGroupDescriptorResponse(
        key=group.key,
        label=group.label,
        fields=[
            _build_field_response(field)
            for field in group.fields
        ],
    )


def _build_field_response(
    field: ConfigurationFieldDescriptor,
) -> ConfigurationFieldDescriptorResponse:
    return ConfigurationFieldDescriptorResponse(
        key=field.key,
        label=field.label,
        description=field.description,
        kind=field.kind,
        minimum=field.minimum,
        maximum=field.maximum,
    )


def _build_rule_response(
    rule: ConfigurationRuleDescriptor,
) -> ConfigurationRuleDescriptorResponse:
    return ConfigurationRuleDescriptorResponse(
        kind=rule.kind,
        group=rule.group,
        fields=list(rule.fields),
        target_field=rule.target_field,
        message=rule.message,
    )
