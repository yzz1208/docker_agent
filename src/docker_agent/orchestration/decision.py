from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, cast

from docker_agent.agent.registry import AgentNotRegistered, AgentRegistry
from docker_agent.orchestration.delegation import (
    AgentCapabilityIndex,
    DelegationContext,
    DelegationPolicy,
    DelegationPolicyError,
)
from docker_agent.rag.llm import ChatModel

OrchestrationAction = Literal["clarify", "direct", "delegate"]

ORCHESTRATION_SYSTEM_PROMPT = """You are the platform orchestration decision model.
Return JSON only. Do not answer the user's technical question and do not invoke any Agent.

Choose exactly one action:
- clarify: there is not enough information to safely choose a specialist/capability.
- direct: send the request directly to one specialist without a cross-Agent handoff.
- delegate: the current specialist should hand off to a different specialist.

Rules:
- Use only Agents and capabilities in the supplied catalog.
- Prefer a specific capability over generic "chat" when one applies.
- Never invent tools, permissions, live access, Agent types, or capabilities.
- If current_agent_type is null, use direct rather than delegate.
- If action is direct and current_agent_type is non-null, target must be that current Agent.
- If action is delegate, current_agent_type must be non-null and target must be different.
- Use clarify when information is insufficient to distinguish the needed specialist/capability.
- clarification must use the same language as the user request.

Return exactly:
{
  "action": "clarify" | "direct" | "delegate",
  "reason": "brief reason",
  "target_agent_type": "registered agent type or null",
  "capability": "declared capability or null",
  "clarification": "question or null"
}
"""


class OrchestrationDecisionError(ValueError):
    """Raised when an orchestration model returns an invalid decision."""


@dataclass(frozen=True, slots=True)
class OrchestrationDecision:
    action: OrchestrationAction
    reason: str
    source_agent_type: str | None
    target_agent_type: str | None
    capability: str | None
    clarification: str | None

    @property
    def requires_user_input(self) -> bool:
        return self.action == "clarify"

    @property
    def is_handoff(self) -> bool:
        return self.action == "delegate"


class OrchestrationDecisionModel:
    """Choose and validate an orchestration action without executing an Agent."""

    def __init__(
        self,
        *,
        registry: AgentRegistry,
        model: ChatModel,
        max_hops: int = 2,
    ) -> None:
        self._registry = registry
        self._model = model
        self._capabilities = AgentCapabilityIndex(registry)
        self._policy = DelegationPolicy(registry=registry, max_hops=max_hops)

    def decide(
        self,
        question: str,
        *,
        context: DelegationContext | None = None,
        source_agent_type: str | None = None,
    ) -> OrchestrationDecision:
        normalized = question.strip()
        if not normalized:
            raise ValueError("question must not be empty")
        active_context = context or DelegationContext(original_query=normalized)
        source = self._resolve_source(active_context, source_agent_type)
        raw = self._model.complete(
            system_prompt=ORCHESTRATION_SYSTEM_PROMPT,
            user_prompt=_build_decision_prompt(
                registry=self._registry,
                question=normalized,
                context=active_context,
                source_agent_type=source,
            ),
        )
        return self.validate(
            raw,
            context=active_context,
            source_agent_type=source,
        )

    def validate(
        self,
        raw: str,
        *,
        context: DelegationContext,
        source_agent_type: str | None = None,
    ) -> OrchestrationDecision:
        source = self._resolve_source(context, source_agent_type)
        payload = _parse_json_object(raw)
        action_raw = str(payload.get("action") or "").strip()
        if action_raw not in {"clarify", "direct", "delegate"}:
            raise OrchestrationDecisionError(
                f"unsupported orchestration action: {action_raw!r}"
            )
        action = cast(OrchestrationAction, action_raw)
        reason = str(payload.get("reason") or "").strip()
        if not reason:
            raise OrchestrationDecisionError("decision requires a non-empty reason")

        target = _optional_string(payload.get("target_agent_type"), "target_agent_type")
        capability = _optional_string(payload.get("capability"), "capability")
        clarification = _optional_string(payload.get("clarification"), "clarification")

        if action == "clarify":
            if not clarification:
                raise OrchestrationDecisionError("clarify requires a clarification question")
            if target is not None or capability is not None:
                raise OrchestrationDecisionError(
                    "clarify must not select an Agent or capability"
                )
            return OrchestrationDecision(
                action=action, reason=reason, source_agent_type=source,
                target_agent_type=None, capability=None, clarification=clarification,
            )

        if clarification is not None:
            raise OrchestrationDecisionError(f"{action} must not include clarification")
        if target is None or capability is None:
            raise OrchestrationDecisionError(
                f"{action} requires target_agent_type and capability"
            )

        try:
            canonical_target = self._registry.get(target).agent_type
            if not self._capabilities.supports(canonical_target, capability):
                raise OrchestrationDecisionError(
                    f"Agent {canonical_target!r} does not expose capability "
                    f"{_canonical_capability(capability)!r}"
                )
            canonical_capability = _canonical_capability(capability)
        except AgentNotRegistered as exc:
            raise OrchestrationDecisionError(
                f"target Agent is not registered: {target!r}"
            ) from exc
        except DelegationPolicyError as exc:
            raise OrchestrationDecisionError(str(exc)) from exc

        if action == "direct":
            if source is not None and canonical_target != source:
                raise OrchestrationDecisionError(
                    "direct cannot change the current Agent; use delegate"
                )
            return OrchestrationDecision(
                action=action, reason=reason, source_agent_type=source,
                target_agent_type=canonical_target,
                capability=canonical_capability, clarification=None,
            )

        if source is None:
            raise OrchestrationDecisionError(
                "delegate requires a current source Agent; use direct for initial dispatch"
            )
        try:
            validated = self._policy.delegate(
                context,
                source_agent_type=source,
                target_agent_type=canonical_target,
                capability=canonical_capability,
                reason=reason,
            )
        except DelegationPolicyError as exc:
            raise OrchestrationDecisionError(str(exc)) from exc
        handoff = validated.handoffs[-1]
        return OrchestrationDecision(
            action=action,
            reason=handoff.reason,
            source_agent_type=handoff.source_agent_type,
            target_agent_type=handoff.target_agent_type,
            capability=handoff.capability,
            clarification=None,
        )

    def _resolve_source(
        self,
        context: DelegationContext,
        source_agent_type: str | None,
    ) -> str | None:
        current = context.current_agent_type
        if source_agent_type is None:
            return current
        try:
            source = self._registry.get(source_agent_type).agent_type
        except AgentNotRegistered as exc:
            raise OrchestrationDecisionError(
                f"source Agent is not registered: {source_agent_type!r}"
            ) from exc
        if current is not None and source != current:
            raise OrchestrationDecisionError(
                f"source Agent must match current context owner {current!r}"
            )
        return source


def _build_decision_prompt(
    *,
    registry: AgentRegistry,
    question: str,
    context: DelegationContext,
    source_agent_type: str | None,
) -> str:
    catalog = [
        {
            "agent_type": descriptor.agent_type,
            "description": descriptor.description,
            "capabilities": list(descriptor.capabilities),
            "toolsets": list(descriptor.toolsets),
        }
        for descriptor in registry.list()
    ]
    state = {
        "original_query": context.original_query,
        "current_agent_type": source_agent_type,
        "hop_count": context.hop_count,
        "visited_agents": list(context.visited_agents),
    }
    return (
        "Agent catalog:\\n"
        + json.dumps(catalog, ensure_ascii=False, sort_keys=True)
        + "\\n\\nOrchestration context:\\n"
        + json.dumps(state, ensure_ascii=False, sort_keys=True)
        + "\\n\\nCurrent user request:\\n"
        + question
    )


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\\n".join(lines).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OrchestrationDecisionError(
            f"orchestration model returned invalid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise OrchestrationDecisionError(
            "orchestration model response must be a JSON object"
        )
    return payload


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise OrchestrationDecisionError(f"{field} must be a string or null")
    return value.strip() or None


def _canonical_capability(value: str) -> str:
    return value.strip().lower().replace("-", "_")


__all__ = [
    "ORCHESTRATION_SYSTEM_PROMPT",
    "OrchestrationAction",
    "OrchestrationDecision",
    "OrchestrationDecisionError",
    "OrchestrationDecisionModel",
]
