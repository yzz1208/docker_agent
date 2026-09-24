from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, cast

from docker_agent.agent.registry import (
    AgentNotRegistered,
    AgentRegistry,
    AgentRegistryError,
)
from docker_agent.observability import stage_timer
from docker_agent.orchestration.delegation import (
    AgentCapabilityIndex,
    DelegationContext,
    DelegationPolicy,
    DelegationPolicyError,
)
from docker_agent.rag.llm import ChatModel

OrchestrationAction = Literal["clarify", "direct", "delegate"]

_DECISION_FIELDS = frozenset(
    {
        "action",
        "reason",
        "target_agent_type",
        "capability",
        "clarification",
    }
)

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
- Use clarify only when missing information would materially change the specialist/capability
  choice or is required for a safe next step. Do not clarify merely because the request is broad.
- Greetings, platform/Agent introductions, general Docker concepts, and ordinary explanatory
  questions should normally route directly to the most suitable chat/documentation capability.
- For follow-up requests such as "continue", "what next", or "still failing", use the supplied
  orchestration context and keep the current specialist unless the new evidence clearly requires
  another registered specialist.
- Prefer making useful progress with the information already provided. Ask one concise
  clarification question only when progress is genuinely blocked.
- Keep the reason concrete and based on the user's request; do not use generic routing boilerplate.
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
        routing_question = _current_user_request(normalized)
        active_context = context or DelegationContext(original_query=routing_question)
        source = self._resolve_source(active_context, source_agent_type)

        if source is None:
            fast_path = _initial_fast_path(routing_question)
            if fast_path is not None:
                agent_type, capability, reason = fast_path
                try:
                    target = self._registry.get(agent_type).agent_type
                except AgentRegistryError:
                    target = None
                if (
                    target is not None
                    and self._capabilities.supports(
                        target,
                        capability,
                    )
                ):
                    return OrchestrationDecision(
                        action="direct",
                        reason=reason,
                        source_agent_type=None,
                        target_agent_type=target,
                        capability=capability,
                        clarification=None,
                    )
        else:
            capability = _current_specialist_fast_path(
                source,
                routing_question,
                original_query=active_context.original_query,
            )
            if (
                capability is not None
                and self._capabilities.supports(source, capability)
            ):
                return OrchestrationDecision(
                    action="direct",
                    reason="当前问题仍属于现有专家能力范围，继续由当前专家处理。",
                    source_agent_type=source,
                    target_agent_type=source,
                    capability=capability,
                    clarification=None,
                )

        with stage_timer("orchestration_decision"):
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
        _validate_decision_fields(payload)
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
        except AgentRegistryError as exc:
            raise OrchestrationDecisionError(str(exc)) from exc
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
        except AgentRegistryError as exc:
            raise OrchestrationDecisionError(str(exc)) from exc
        if current is not None and source != current:
            raise OrchestrationDecisionError(
                f"source Agent must match current context owner {current!r}"
            )
        return source


def _current_user_request(question: str) -> str:
    """Extract the live user turn from the bounded conversation wrapper."""

    marker = "当前用户消息：\n"
    if marker not in question:
        return question
    current = question.rsplit(marker, 1)[1].strip()
    return current or question


def _current_specialist_fast_path(
    source_agent_type: str,
    question: str,
    *,
    original_query: str,
) -> str | None:
    if source_agent_type == "docker_support":
        if _is_initial_infrastructure_incident_request(question):
            return None
        if _is_initial_runtime_request(question):
            return "runtime_diagnostics"
        if _is_initial_docker_docs_request(question):
            return "documentation_qa"
        if _is_initial_lightweight_request(question):
            return "chat"
        if _is_short_followup(question):
            if _is_initial_runtime_request(original_query):
                return "runtime_diagnostics"
            if _is_initial_docker_docs_request(original_query):
                return "documentation_qa"
            return None

    if source_agent_type == "infrastructure_troubleshooter":
        if _is_initial_runtime_request(question):
            return None
        if _is_initial_lightweight_request(question):
            return "chat"
        if _is_initial_infrastructure_incident_request(question):
            return "incident_triage"
        if (
            _is_short_followup(question)
            and _is_initial_infrastructure_incident_request(
                original_query
            )
        ):
            return "incident_triage"

    return None


def _is_short_followup(question: str) -> bool:
    normalized = " ".join(question.strip().split())
    lowered = normalized.lower()
    followup_signals = (
        "继续",
        "下一步",
        "然后呢",
        "那",
        "还有",
        "再看",
        "再查",
        "what next",
        "continue",
        "then",
        "still",
    )
    return len(normalized) <= 80 and any(
        lowered.startswith(signal)
        for signal in followup_signals
    )


def _initial_fast_path(
    question: str,
) -> tuple[str, str, str] | None:
    if _is_initial_lightweight_request(question):
        return (
            "docker_support",
            "chat",
            "轻量平台会话无需模型编排，直接交给 Docker 支持。",
        )
    if _is_initial_infrastructure_incident_request(question):
        return (
            "infrastructure_troubleshooter",
            "incident_triage",
            "明确的服务级故障信号直接进入基础设施排障。",
        )
    if _is_initial_runtime_request(question):
        return (
            "docker_support",
            "runtime_diagnostics",
            "明确的当前 Docker 运行时问题直接进入只读诊断。",
        )
    if _is_initial_docker_docs_request(question):
        return (
            "docker_support",
            "documentation_qa",
            "明确的 Docker 文档问题直接进入文档问答。",
        )
    return None


def _is_initial_infrastructure_incident_request(
    question: str,
) -> bool:
    lowered = question.lower()
    incident_signals = (
        " 503",
        "503 ",
        "502 ",
        "504 ",
        "5xx",
        "依赖超时",
        "dependency timeout",
        "service outage",
        "服务不可用",
    )
    service_signals = (
        "api",
        "服务",
        "service",
        "依赖",
        "dependency",
        "checkout",
    )
    return any(
        signal in f" {lowered} "
        for signal in incident_signals
    ) and any(signal in lowered for signal in service_signals)


def _is_initial_runtime_request(question: str) -> bool:
    lowered = question.lower()
    current_state_signals = (
        "最近日志",
        "查看日志",
        "看一下日志",
        "运行状态",
        "是否运行",
        "还在运行",
        "cpu 和内存",
        "cpu和内存",
        "memory usage",
        "current status",
        "recent logs",
        "docker ps",
        "docker logs",
        "docker inspect",
    )
    return any(signal in lowered for signal in current_state_signals)


def _is_initial_docker_docs_request(question: str) -> bool:
    lowered = question.lower()
    docs_signals = (
        "docker volume",
        "bind mount",
        "docker compose",
        "dockerfile",
        "docker daemon",
        "docker image",
        "docker network",
        "docker registry",
        "存储卷",
        "绑定挂载",
        "镜像",
        "容器网络",
    )
    return any(signal in lowered for signal in docs_signals)


def _is_initial_lightweight_request(question: str) -> bool:
    normalized = " ".join(question.strip().split())
    lowered = normalized.lower().strip(" .!?！？。")
    compact = lowered.replace(" ", "")
    return lowered in {
        "hi",
        "hello",
        "hey",
        "你好",
        "您好",
        "嗨",
        "哈喽",
    } or compact in {
        "介绍自己",
        "简单介绍自己",
        "介绍一下自己",
        "你是谁",
        "你能做什么",
        "你可以做什么",
        "介绍一下这个平台",
        "介绍这个平台",
        "这个平台能做什么",
        "怎么使用这个平台",
        "如何使用这个平台",
        "帮助",
        "help",
        "whatareyou",
        "whatcanyoudo",
        "howtousethisplatform",
    }


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
        "Agent catalog:\n"
        + json.dumps(catalog, ensure_ascii=False, sort_keys=True)
        + "\n\nOrchestration context:\n"
        + json.dumps(state, ensure_ascii=False, sort_keys=True)
        + "\n\nCurrent user request:\n"
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
        text = "\n".join(lines).strip()
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


def _validate_decision_fields(payload: dict[str, Any]) -> None:
    keys = set(payload)
    missing = sorted(_DECISION_FIELDS - keys)
    unexpected = sorted(keys - _DECISION_FIELDS)
    if missing:
        raise OrchestrationDecisionError(
            "orchestration decision is missing fields: "
            + ", ".join(missing)
        )
    if unexpected:
        raise OrchestrationDecisionError(
            "orchestration decision contains unexpected fields: "
            + ", ".join(unexpected)
        )


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
