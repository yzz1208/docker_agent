from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, cast

from docker_agent.rag.llm import ChatModel
from docker_agent.tools.docker_cli import validate_container_ref

AgentRoute = Literal[
    "general_chat",
    "docs_only",
    "runtime_tools",
    "clarify",
]
DockerToolName = Literal[
    "docker_info",
    "docker_ps",
    "docker_inspect",
    "docker_logs",
    "docker_stats",
]

_ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        "docker_info",
        "docker_ps",
        "docker_inspect",
        "docker_logs",
        "docker_stats",
    }
)
_CONTAINER_TOOLS: frozenset[str] = frozenset(
    {"docker_inspect", "docker_logs", "docker_stats"}
)

ROUTER_SYSTEM_PROMPT = """You route Docker support questions.
Return JSON only. Never answer the Docker question itself.

Available paths:
1. general_chat: greetings, assistant self-introduction, platform capability questions,
   usage guidance, conversational acknowledgements, or lightweight meta conversation.
2. docs_only: Docker documentation is sufficient for conceptual, configuration, command,
   best-practice, or how-to questions that do not depend on this user's current runtime.
3. runtime_tools: the question asks about the user's current Docker daemon, containers,
   resource usage, logs, exit/restart state, or other local runtime facts.
4. clarify: runtime evidence is required but a specific container is needed and the user
   did not provide an exact container name or ID.

Allowed read-only tools:
- docker_info: current Docker daemon/system information
- docker_ps: list current/stopped containers
- docker_inspect: inspect one named container
- docker_logs: recent logs for one named container
- docker_stats: one current CPU/memory snapshot for one named container

Rules:
- Never invent a container name or ID.
- Only copy container_ref from the user's question when it is explicitly present.
- Greetings such as "hello", "你好", "介绍一下自己", "你能做什么", or "怎么使用这个系统"
  are general_chat unless they also contain a concrete technical request.
- General Docker questions such as "what is a volume?" or "how does depends_on work?" are docs_only.
- Do not use clarify merely because a message is conversational or asks about the assistant.
- Choose the smallest sufficient read-only tool set; do not add tools just in case.
- Current CPU/memory usage for a named container needs docker_stats.
- A direct question asking whether a container was OOM-killed needs docker_inspect only; State.OOMKilled and ExitCode are sufficient evidence. Add docker_logs only when the user asks for broader root-cause diagnosis beyond the OOM check.
- Why a named container crashed/restarted usually needs docker_inspect and docker_logs.
- Current daemon/system status usually needs docker_info.
- If the user asks which containers exist, use docker_ps.
- If a container-specific runtime question has no exact container reference, choose clarify.
- Write clarification in the same language as the user question.
- For runtime_tools, set use_docs=true only when Docker documentation is useful for the
  user's requested how-to or remediation. Otherwise set use_docs=false.
- Current measurements, logs, and root-cause questions that can be answered directly from
  runtime evidence usually use_docs=false.
- Do not request or plan write/destructive tools.

Return exactly:
{
  "route": "general_chat" | "docs_only" | "runtime_tools" | "clarify",
  "reason": "brief reason",
  "container_ref": "exact name/id from question or null",
  "tools": ["allowed tool names"],
  "clarification": "question to ask user or null",
  "use_docs": true | false
}
"""


class AgentRoutingError(ValueError):
    """Raised when a route model returns an invalid or unsafe plan."""


@dataclass(frozen=True, slots=True)
class AgentRouteDecision:
    route: AgentRoute
    reason: str
    container_ref: str | None
    tools: tuple[DockerToolName, ...]
    clarification: str | None
    use_docs: bool


def route_question(question: str, model: ChatModel) -> AgentRouteDecision:
    """Classify whether a question needs docs, runtime evidence, or clarification."""

    question = question.strip()
    if not question:
        raise ValueError("question must not be empty")

    raw = model.complete(
        system_prompt=ROUTER_SYSTEM_PROMPT,
        user_prompt=f"User question:\n{question}",
    )
    decision = parse_route_decision(raw)
    if decision.container_ref is not None and decision.container_ref not in question:
        raise AgentRoutingError(
            "Router invented a container_ref that does not appear in the user question"
        )
    return decision


def parse_route_decision(raw: str) -> AgentRouteDecision:
    """Parse and strictly validate the model's JSON routing decision."""

    payload = _parse_json_object(raw)
    route_raw = str(payload.get("route") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    clarification_raw = payload.get("clarification")
    container_raw = payload.get("container_ref")
    tools_raw = payload.get("tools")
    use_docs_raw = payload.get("use_docs")

    if route_raw not in {
        "general_chat",
        "docs_only",
        "runtime_tools",
        "clarify",
    }:
        raise AgentRoutingError(f"Unsupported route: {route_raw!r}")
    route = cast(AgentRoute, route_raw)

    if not reason:
        raise AgentRoutingError("Route decision requires a non-empty reason")
    if not isinstance(tools_raw, list):
        raise AgentRoutingError("Route decision tools must be a list")
    if use_docs_raw is None:
        use_docs = route == "docs_only"
    elif isinstance(use_docs_raw, bool):
        use_docs = use_docs_raw
    else:
        raise AgentRoutingError("use_docs must be boolean")

    tools: list[DockerToolName] = []
    seen: set[str] = set()
    for item in tools_raw:
        tool_raw = str(item).strip()
        if tool_raw not in _ALLOWED_TOOLS:
            raise AgentRoutingError(f"Unsupported Docker tool: {tool_raw!r}")
        if tool_raw in seen:
            continue
        seen.add(tool_raw)
        tools.append(cast(DockerToolName, tool_raw))

    container_ref: str | None = None
    if container_raw is not None:
        if not isinstance(container_raw, str):
            raise AgentRoutingError("container_ref must be a string or null")
        try:
            container_ref = validate_container_ref(container_raw)
        except ValueError as exc:
            raise AgentRoutingError(str(exc)) from exc

    clarification: str | None = None
    if clarification_raw is not None:
        if not isinstance(clarification_raw, str):
            raise AgentRoutingError("clarification must be a string or null")
        clarification = clarification_raw.strip() or None

    if route == "general_chat":
        if tools:
            raise AgentRoutingError(
                "general_chat route must not contain runtime tools"
            )
        if container_ref is not None:
            raise AgentRoutingError(
                "general_chat route must not contain container_ref"
            )
        clarification = None
        use_docs = False
    elif route == "docs_only":
        if tools:
            raise AgentRoutingError("docs_only route must not contain runtime tools")
        if container_ref is not None:
            raise AgentRoutingError("docs_only route must not contain container_ref")
        clarification = None
        use_docs = True
    elif route == "clarify":
        # Safe normalization: the model may mention tools it would use after
        # clarification, but no runtime command is permitted on this turn.
        tools = []
        container_ref = None
        use_docs = False
        if not clarification:
            raise AgentRoutingError("clarify route requires a clarification question")
    else:
        if not tools:
            raise AgentRoutingError("runtime_tools route requires at least one tool")
        if any(tool in _CONTAINER_TOOLS for tool in tools) and container_ref is None:
            raise AgentRoutingError(
                "Container-specific runtime tools require an explicit container_ref"
            )
        clarification = None

    return AgentRouteDecision(
        route=route,
        reason=reason,
        container_ref=container_ref,
        tools=tuple(tools),
        clarification=clarification,
        use_docs=use_docs,
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
        raise AgentRoutingError(f"Router returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise AgentRoutingError("Router response must be a JSON object")
    return payload
