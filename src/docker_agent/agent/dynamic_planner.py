from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, cast

from docker_agent.agent.evidence import RuntimeEvidenceContext
from docker_agent.agent.router import DockerToolName
from docker_agent.rag.llm import ChatModel

DynamicAction = Literal["tool", "finish"]

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

PLANNER_SYSTEM_PROMPT = """You are the runtime planner for a Docker support agent.
Choose exactly one next action. Return JSON only. Never answer the user directly.

You operate after a safe router has already decided that local runtime evidence is needed.

Allowed read-only tools:
- docker_info: current Docker daemon/system information
- docker_ps: list current and stopped containers
- docker_inspect: inspect one named container
- docker_logs: recent logs for one named container
- docker_stats: one current CPU/memory snapshot for one named container

Rules:
- Choose the smallest sufficient next step.
- Use one tool at a time, observe its result, then decide again.
- Never request a tool that already appears in Used tools.
- Never request write/destructive actions.
- Never invent or change the container_ref supplied by the validated router.
- For a direct current CPU/memory question, docker_stats is usually sufficient.
- For a direct OOMKilled check, docker_inspect is usually sufficient.
- For crash/restart diagnosis, inspect state first.
- A non-zero ExitCode plus a restart policy explains why Docker restarts a container, but
  it does not by itself explain why the container process keeps failing. If the user asks
  why a container keeps restarting, request docker_logs after inspect unless inspect already
  contains a direct root cause such as OOMKilled=true or a concrete State.Error.
- Do not finish a restart root-cause investigation merely because RestartPolicy=on-failure
  and ExitCode is non-zero; identify the underlying process failure when evidence allows.
- When the accumulated runtime evidence is sufficient, return action=finish.
- A failed tool result is evidence. Decide whether another allowed read-only tool can help;
  otherwise finish so the final answer can report the limitation.

Return exactly:
{
  "action": "tool" | "finish",
  "tool": "allowed tool name or null",
  "reason": "brief reason"
}
"""


class DynamicPlannerError(ValueError):
    """Raised when a dynamic planner returns an invalid or unsafe action."""


@dataclass(frozen=True, slots=True)
class DynamicRuntimeDecision:
    action: DynamicAction
    tool: DockerToolName | None
    reason: str


def plan_runtime_action(
    *,
    question: str,
    container_ref: str | None,
    used_tools: tuple[DockerToolName, ...],
    evidence: RuntimeEvidenceContext,
    model: ChatModel,
) -> DynamicRuntimeDecision:
    """Ask the planner for exactly one validated next runtime action."""

    container_text = container_ref or "<none>"
    used_text = ", ".join(used_tools) if used_tools else "<none>"
    evidence_text = evidence.text or "<no runtime evidence yet>"

    raw = model.complete(
        system_prompt=PLANNER_SYSTEM_PROMPT,
        user_prompt=(
            f"User question:\n{question}\n\n"
            f"Validated container_ref:\n{container_text}\n\n"
            f"Used tools:\n{used_text}\n\n"
            f"Runtime evidence so far:\n{evidence_text}"
        ),
    )
    return parse_runtime_decision(
        raw,
        container_ref=container_ref,
        used_tools=used_tools,
    )


def parse_runtime_decision(
    raw: str,
    *,
    container_ref: str | None,
    used_tools: tuple[DockerToolName, ...] = (),
) -> DynamicRuntimeDecision:
    """Parse and enforce the dynamic planner safety boundary."""

    payload = _parse_json_object(raw)
    action_raw = str(payload.get("action") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    tool_raw = payload.get("tool")

    if action_raw not in {"tool", "finish"}:
        raise DynamicPlannerError(f"Unsupported planner action: {action_raw!r}")
    if not reason:
        raise DynamicPlannerError("Planner decision requires a non-empty reason")

    action = cast(DynamicAction, action_raw)
    if action == "finish":
        if tool_raw not in {None, ""}:
            raise DynamicPlannerError("finish action must not contain a tool")
        return DynamicRuntimeDecision(action="finish", tool=None, reason=reason)

    if not isinstance(tool_raw, str):
        raise DynamicPlannerError("tool action requires a tool name")
    tool_name = tool_raw.strip()
    if tool_name not in _ALLOWED_TOOLS:
        raise DynamicPlannerError(f"Unsupported Docker tool: {tool_name!r}")

    tool = cast(DockerToolName, tool_name)
    if tool in used_tools:
        raise DynamicPlannerError(f"Planner repeated already-used tool: {tool}")
    if tool in _CONTAINER_TOOLS and container_ref is None:
        raise DynamicPlannerError(
            f"{tool} requires a validated container_ref from the router"
        )

    return DynamicRuntimeDecision(action="tool", tool=tool, reason=reason)


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
        raise DynamicPlannerError(f"Planner returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise DynamicPlannerError("Planner response must be a JSON object")
    return payload
