from __future__ import annotations

from dataclasses import dataclass

from docker_agent.agent.configuration_schema import (
    ConfigurationFieldDescriptor,
    ConfigurationGroupDescriptor,
    ConfigurationRuleDescriptor,
)


class AgentRegistryError(ValueError):
    """Base error for invalid Agent registry operations."""


class AgentAlreadyRegistered(AgentRegistryError):
    """Raised when one Agent type is registered more than once."""


class AgentNotRegistered(AgentRegistryError):
    """Raised when a runtime Agent type is not registered."""


def _normalize_agent_type(agent_type: str) -> str:
    if not isinstance(agent_type, str):
        raise AgentRegistryError(
            "agent_type must be a string"
        )

    normalized = agent_type.strip().lower().replace("-", "_")
    if not normalized:
        raise AgentRegistryError(
            "agent_type must not be empty"
        )

    allowed = set(
        "abcdefghijklmnopqrstuvwxyz0123456789_"
    )
    if any(character not in allowed for character in normalized):
        raise AgentRegistryError(
            "agent_type may contain only lowercase letters, "
            "numbers, underscores, and hyphens"
        )
    return normalized


def _validate_labels(
    values: tuple[str, ...],
    *,
    field: str,
) -> None:
    if len(set(values)) != len(values):
        raise AgentRegistryError(
            f"{field} must not contain duplicates"
        )
    for value in values:
        if not value.strip():
            raise AgentRegistryError(
                f"{field} must not contain empty values"
            )


@dataclass(frozen=True, slots=True)
class AgentDescriptor:
    """Immutable runtime metadata for one supported Agent type."""

    agent_type: str
    display_name: str
    description: str
    capabilities: tuple[str, ...]
    knowledge_sources: tuple[str, ...]
    toolsets: tuple[str, ...]
    worker_roles: tuple[str, ...]
    configuration_schema: tuple[
        ConfigurationGroupDescriptor,
        ...,
    ]
    configuration_rules: tuple[
        ConfigurationRuleDescriptor,
        ...,
    ] = ()
    default_enabled: bool = True

    @property
    def configuration_groups(self) -> tuple[str, ...]:
        return tuple(
            group.key
            for group in self.configuration_schema
        )

    def __post_init__(self) -> None:
        normalized_type = _normalize_agent_type(self.agent_type)
        if normalized_type != self.agent_type:
            raise AgentRegistryError(
                "agent_type must already be normalized"
            )
        if not self.display_name.strip():
            raise AgentRegistryError(
                "display_name must not be empty"
            )
        if not self.description.strip():
            raise AgentRegistryError(
                "description must not be empty"
            )

        for label, values in {
            "capabilities": self.capabilities,
            "knowledge_sources": self.knowledge_sources,
            "toolsets": self.toolsets,
            "worker_roles": self.worker_roles,
            "configuration_groups": self.configuration_groups,
        }.items():
            _validate_labels(values, field=label)


class AgentRegistry:
    """In-process catalog of runtime-supported Agent types."""

    def __init__(
        self,
        descriptors: tuple[AgentDescriptor, ...] = (),
    ) -> None:
        self._descriptors: dict[str, AgentDescriptor] = {}
        for descriptor in descriptors:
            self.register(descriptor)

    def register(
        self,
        descriptor: AgentDescriptor,
    ) -> None:
        agent_type = descriptor.agent_type
        if agent_type in self._descriptors:
            raise AgentAlreadyRegistered(agent_type)
        self._descriptors[agent_type] = descriptor

    def get(self, agent_type: str) -> AgentDescriptor:
        normalized = _normalize_agent_type(agent_type)
        try:
            return self._descriptors[normalized]
        except KeyError as exc:
            raise AgentNotRegistered(normalized) from exc

    def list(self) -> tuple[AgentDescriptor, ...]:
        return tuple(
            self._descriptors[key]
            for key in sorted(self._descriptors)
        )

    def contains(self, agent_type: str) -> bool:
        try:
            normalized = _normalize_agent_type(agent_type)
        except AgentRegistryError:
            return False
        return normalized in self._descriptors


DOCKER_SUPPORT_DESCRIPTOR = AgentDescriptor(
    agent_type="docker_support",
    display_name="Docker Support",
    description=(
        "Docker technical support Agent with documentation retrieval, "
        "read-only runtime diagnostics, and LangGraph worker orchestration."
    ),
    capabilities=(
        "chat",
        "documentation_qa",
        "runtime_diagnostics",
        "multi_agent_supervision",
    ),
    knowledge_sources=("docker_docs",),
    toolsets=("docker_read_only",),
    worker_roles=(
        "knowledge",
        "runtime",
        "diagnosis",
    ),
    configuration_schema=(
        ConfigurationGroupDescriptor(
            key="model_settings",
            label="Model",
            fields=(
                ConfigurationFieldDescriptor(
                    key="model_name",
                    settings_name="model_name",
                    label="Model name",
                    description=(
                        "OpenAI-compatible model identifier used by the Agent."
                    ),
                    kind="string",
                ),
                ConfigurationFieldDescriptor(
                    key="temperature",
                    settings_name="model_temperature",
                    label="Temperature",
                    description="Sampling temperature for model responses.",
                    kind="number",
                    minimum=0,
                    maximum=2,
                ),
                ConfigurationFieldDescriptor(
                    key="max_tokens",
                    settings_name="model_max_tokens",
                    label="Max tokens",
                    description=(
                        "Maximum generated tokens when the provider supports it."
                    ),
                    kind="integer",
                    minimum=1,
                ),
                ConfigurationFieldDescriptor(
                    key="timeout_seconds",
                    settings_name="model_timeout_seconds",
                    label="Model timeout",
                    description=(
                        "Maximum seconds allowed for one model request."
                    ),
                    kind="number",
                    minimum=0.001,
                ),
                ConfigurationFieldDescriptor(
                    key="max_retries",
                    settings_name="model_max_retries",
                    label="Model retries",
                    description=(
                        "Retry attempts after a retryable model failure."
                    ),
                    kind="integer",
                    minimum=0,
                ),
                ConfigurationFieldDescriptor(
                    key="retry_backoff_seconds",
                    settings_name="model_retry_backoff_seconds",
                    label="Retry backoff",
                    description="Delay between model retries in seconds.",
                    kind="number",
                    minimum=0,
                ),
            ),
        ),
        ConfigurationGroupDescriptor(
            key="retrieval_settings",
            label="Retrieval",
            fields=(
                ConfigurationFieldDescriptor(
                    key="top_k",
                    settings_name="retrieval_candidate_k",
                    label="Candidate top K",
                    description=(
                        "Hybrid retrieval candidates kept before reranking."
                    ),
                    kind="integer",
                    minimum=1,
                ),
                ConfigurationFieldDescriptor(
                    key="rrf_k",
                    settings_name="retrieval_rrf_k",
                    label="RRF K",
                    description=(
                        "Reciprocal-rank-fusion smoothing constant."
                    ),
                    kind="integer",
                    minimum=0,
                ),
                ConfigurationFieldDescriptor(
                    key="dense_weight",
                    settings_name="retrieval_dense_weight",
                    label="Dense weight",
                    description=(
                        "Weight applied to dense retrieval ranking."
                    ),
                    kind="number",
                    minimum=0,
                ),
                ConfigurationFieldDescriptor(
                    key="keyword_weight",
                    settings_name="retrieval_keyword_weight",
                    label="Keyword weight",
                    description=(
                        "Weight applied to keyword retrieval ranking."
                    ),
                    kind="number",
                    minimum=0,
                ),
                ConfigurationFieldDescriptor(
                    key="rerank_top_k",
                    settings_name="rerank_top_k",
                    label="Rerank top K",
                    description=(
                        "Final candidates retained after reranking."
                    ),
                    kind="integer",
                    minimum=1,
                ),
                ConfigurationFieldDescriptor(
                    key="context_max_chars",
                    settings_name="rag_context_max_chars",
                    label="Context max chars",
                    description=(
                        "Maximum documentation context passed to the answer model."
                    ),
                    kind="integer",
                    minimum=1,
                ),
            ),
        ),
        ConfigurationGroupDescriptor(
            key="runtime_settings",
            label="Runtime",
            fields=(
                ConfigurationFieldDescriptor(
                    key="max_steps",
                    settings_name="dynamic_runtime_max_steps",
                    label="Runtime max steps",
                    description=(
                        "Maximum dynamic runtime workflow steps."
                    ),
                    kind="integer",
                    minimum=1,
                ),
                ConfigurationFieldDescriptor(
                    key="tool_timeout_seconds",
                    settings_name="docker_tool_timeout_seconds",
                    label="Docker tool timeout",
                    description=(
                        "Maximum seconds allowed for one Docker tool call."
                    ),
                    kind="number",
                    minimum=0.001,
                ),
                ConfigurationFieldDescriptor(
                    key="logs_max_lines",
                    settings_name="docker_logs_max_lines",
                    label="Log line limit",
                    description=(
                        "Maximum Docker log lines collected per tool call."
                    ),
                    kind="integer",
                    minimum=1,
                ),
                ConfigurationFieldDescriptor(
                    key="evidence_max_chars",
                    settings_name="runtime_evidence_max_chars",
                    label="Evidence max chars",
                    description=(
                        "Maximum runtime evidence characters retained "
                        "for synthesis."
                    ),
                    kind="integer",
                    minimum=1,
                ),
            ),
        ),
    ),
    configuration_rules=(
        ConfigurationRuleDescriptor(
            kind="less_equal",
            group="retrieval_settings",
            fields=("rerank_top_k", "top_k"),
            target_field="rerank_top_k",
            message=(
                "retrieval_settings.rerank_top_k must not exceed top_k"
            ),
        ),
        ConfigurationRuleDescriptor(
            kind="not_all_zero",
            group="retrieval_settings",
            fields=("dense_weight", "keyword_weight"),
            target_field="keyword_weight",
            message=(
                "retrieval dense_weight and keyword_weight cannot both be zero"
            ),
        ),
    ),
)


def build_agent_registry() -> AgentRegistry:
    """Build the default runtime Agent registry."""

    return AgentRegistry((DOCKER_SUPPORT_DESCRIPTOR,))


