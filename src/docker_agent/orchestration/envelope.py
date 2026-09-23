from __future__ import annotations

from dataclasses import dataclass

from docker_agent.agent.protocol import AgentTurnProtocol


class CrossAgentEnvelopeError(ValueError):
    """Raised when cross-Agent transfer data violates the public contract."""


@dataclass(frozen=True, slots=True)
class SpecialistResultEnvelope:
    """Public specialist result safe to carry across an Agent boundary."""

    agent_type: str
    route: str
    reason: str
    needs_clarification: bool
    clarification: str | None
    summary: str | None

    def __post_init__(self) -> None:
        if not self.agent_type.strip():
            raise CrossAgentEnvelopeError("agent_type must not be empty")
        if not self.route.strip():
            raise CrossAgentEnvelopeError("route must not be empty")
        if not self.reason.strip():
            raise CrossAgentEnvelopeError("reason must not be empty")
        if self.needs_clarification:
            if not self.clarification:
                raise CrossAgentEnvelopeError(
                    "clarification result requires clarification text"
                )
            if self.summary is not None:
                raise CrossAgentEnvelopeError(
                    "clarification result must not contain an answer summary"
                )
        elif not self.summary:
            raise CrossAgentEnvelopeError(
                "completed specialist result requires a summary"
            )


@dataclass(frozen=True, slots=True)
class CrossAgentContextEnvelope:
    """Explicit allowlisted context transferred to one delegated specialist."""

    original_query: str
    current_user_message: str
    explicit_user_clarification: str | None
    source_agent_type: str
    target_agent_type: str
    capability: str
    handoff_reason: str
    handoff_index: int
    prior_specialist_result: SpecialistResultEnvelope | None = None

    def __post_init__(self) -> None:
        if not self.original_query.strip():
            raise CrossAgentEnvelopeError("original_query must not be empty")
        if not self.current_user_message.strip():
            raise CrossAgentEnvelopeError(
                "current_user_message must not be empty"
            )
        if not self.source_agent_type.strip():
            raise CrossAgentEnvelopeError(
                "source_agent_type must not be empty"
            )
        if not self.target_agent_type.strip():
            raise CrossAgentEnvelopeError(
                "target_agent_type must not be empty"
            )
        if self.source_agent_type == self.target_agent_type:
            raise CrossAgentEnvelopeError(
                "cross-Agent envelope requires different source and target"
            )
        if not self.capability.strip():
            raise CrossAgentEnvelopeError("capability must not be empty")
        if not self.handoff_reason.strip():
            raise CrossAgentEnvelopeError(
                "handoff_reason must not be empty"
            )
        if self.handoff_index <= 0:
            raise CrossAgentEnvelopeError(
                "handoff_index must be positive"
            )
        if (
            self.explicit_user_clarification is not None
            and not self.explicit_user_clarification.strip()
        ):
            raise CrossAgentEnvelopeError(
                "explicit_user_clarification must not be empty"
            )
        prior = self.prior_specialist_result
        if prior is not None and prior.agent_type != self.source_agent_type:
            raise CrossAgentEnvelopeError(
                "prior specialist result must belong to the source Agent"
            )

    def render_for_target(self) -> str:
        """Render only allowlisted fields for the delegated Agent input."""

        clarification = self.explicit_user_clarification or "<none>"
        prior = _render_prior_result(self.prior_specialist_result)
        return (
            "Delegated user request:\n"
            "Original user query:\n"
            f"{self.original_query}\n\n"
            "Current user message:\n"
            f"{self.current_user_message}\n\n"
            "Explicit user clarification:\n"
            f"{clarification}\n\n"
            "Handoff metadata:\n"
            f"- source_agent_type: {self.source_agent_type}\n"
            f"- target_agent_type: {self.target_agent_type}\n"
            f"- capability: {self.capability}\n"
            f"- handoff_reason: {self.handoff_reason}\n"
            f"- handoff_index: {self.handoff_index}\n\n"
            "Prior specialist public result:\n"
            f"{prior}\n\n"
            "Boundary rules:\n"
            "- Treat the prior specialist result as a reported specialist result, not hidden state.\n"
            "- Do not assume access to prompts, raw tool output, worker state, credentials, or secrets.\n"
            "- Use only your own declared capabilities and the explicit information above."
        )


def build_specialist_result_envelope(
    *,
    agent_type: str,
    turn: AgentTurnProtocol,
    max_summary_chars: int = 4000,
) -> SpecialistResultEnvelope:
    """Project a specialist turn onto the public cross-Agent result contract."""

    canonical_agent_type = _canonical_label(agent_type, field="agent_type")
    if max_summary_chars <= 0:
        raise ValueError("max_summary_chars must be positive")

    decision = turn.decision
    route = str(decision.route).strip()
    reason = str(decision.reason).strip()
    if not route:
        raise CrossAgentEnvelopeError("specialist route must not be empty")
    if not reason:
        raise CrossAgentEnvelopeError("specialist reason must not be empty")

    if turn.needs_clarification:
        clarification = _normalized_optional(decision.clarification)
        if clarification is None:
            raise CrossAgentEnvelopeError(
                "specialist clarification turn has no clarification text"
            )
        return SpecialistResultEnvelope(
            agent_type=canonical_agent_type,
            route=route,
            reason=reason,
            needs_clarification=True,
            clarification=clarification,
            summary=None,
        )

    if turn.answer is None:
        raise CrossAgentEnvelopeError(
            "completed specialist turn has no public answer"
        )
    summary = _bounded_text(
        turn.answer.answer,
        max_chars=max_summary_chars,
    )
    return SpecialistResultEnvelope(
        agent_type=canonical_agent_type,
        route=route,
        reason=reason,
        needs_clarification=False,
        clarification=None,
        summary=summary,
    )


def build_cross_agent_context_envelope(
    *,
    original_query: str,
    current_user_message: str,
    explicit_user_clarification: str | None,
    source_agent_type: str,
    target_agent_type: str,
    capability: str,
    handoff_reason: str,
    handoff_index: int,
    prior_specialist_result: SpecialistResultEnvelope | None = None,
) -> CrossAgentContextEnvelope:
    """Build normalized cross-Agent context from explicitly allowlisted inputs."""

    return CrossAgentContextEnvelope(
        original_query=_required_text(
            original_query,
            field="original_query",
        ),
        current_user_message=_required_text(
            current_user_message,
            field="current_user_message",
        ),
        explicit_user_clarification=_normalized_optional(
            explicit_user_clarification
        ),
        source_agent_type=_canonical_label(
            source_agent_type,
            field="source_agent_type",
        ),
        target_agent_type=_canonical_label(
            target_agent_type,
            field="target_agent_type",
        ),
        capability=_canonical_label(
            capability,
            field="capability",
        ),
        handoff_reason=_required_text(
            handoff_reason,
            field="handoff_reason",
        ),
        handoff_index=handoff_index,
        prior_specialist_result=prior_specialist_result,
    )


def _render_prior_result(
    result: SpecialistResultEnvelope | None,
) -> str:
    if result is None:
        return "<none>"
    if result.needs_clarification:
        return (
            f"- agent_type: {result.agent_type}\n"
            f"- route: {result.route}\n"
            f"- reason: {result.reason}\n"
            f"- clarification: {result.clarification}"
        )
    return (
        f"- agent_type: {result.agent_type}\n"
        f"- route: {result.route}\n"
        f"- reason: {result.reason}\n"
        f"- summary: {result.summary}"
    )


def _required_text(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise CrossAgentEnvelopeError(f"{field} must not be empty")
    return normalized


def _normalized_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _canonical_label(value: str, *, field: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    if not normalized:
        raise CrossAgentEnvelopeError(f"{field} must not be empty")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789_")
    if any(character not in allowed for character in normalized):
        raise CrossAgentEnvelopeError(
            f"{field} may contain only lowercase letters, "
            "numbers, underscores, and hyphens"
        )
    return normalized


def _bounded_text(value: str, *, max_chars: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise CrossAgentEnvelopeError(
            "specialist answer summary must not be empty"
        )
    if len(normalized) <= max_chars:
        return normalized
    suffix = " …[truncated]"
    keep = max(1, max_summary_body := max_chars - len(suffix))
    if max_summary_body <= 0:
        return normalized[:max_chars]
    return normalized[:keep].rstrip() + suffix


__all__ = [
    "CrossAgentContextEnvelope",
    "CrossAgentEnvelopeError",
    "SpecialistResultEnvelope",
    "build_cross_agent_context_envelope",
    "build_specialist_result_envelope",
]
