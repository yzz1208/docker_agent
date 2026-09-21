from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, cast

from docker_agent.agent.answer import AgentAnswer
from docker_agent.config import Settings, get_settings
from docker_agent.rag.llm import ChatModel, OpenAICompatibleChatClient

InfrastructureRoute = Literal["triage", "clarify"]

TRIAGE_ROUTER_SYSTEM_PROMPT = """You route infrastructure incident-triage questions.
Return JSON only. Do not answer the incident itself.

This Agent has no live system access and no Docker/runtime tools. It can only reason from
facts the user provides.

Choose:
- triage: the user identifies an affected service/system and provides a concrete symptom,
  failure, error, latency issue, availability issue, or other observable incident signal.
- clarify: the request is too vague to identify both the affected component and the observed
  symptom.

Do not ask for credentials, secrets, API keys, tokens, or destructive access.
Prefer one concise clarification question requesting the minimum missing operational fact.
Write clarification in the same language as the user.

Return exactly:
{
  "route": "triage" | "clarify",
  "reason": "brief reason",
  "clarification": "question or null"
}
"""

TRIAGE_ANSWER_SYSTEM_PROMPT = """You are an infrastructure incident triage specialist.
You have no live access to the user's hosts, services, logs, metrics, network, cloud account,
or containers. Treat only user-provided observations as observed facts.

Use this embedded triage playbook:
1. Establish scope: affected service/component, users, environment, and blast radius.
2. Establish timeline: onset, duration, intermittent vs continuous, and recent changes.
3. Separate observations from hypotheses.
4. Consider a small set of plausible categories only when supported by the observations:
   application/configuration change, dependency failure, resource pressure, network/DNS,
   authentication/authorization, storage, or external service degradation.
5. Recommend the smallest safe next checks that would discriminate between hypotheses.
6. Never invent logs, metrics, host state, commands already executed, or root cause.
7. Do not request secrets or credentials.
8. Clearly say when the root cause is not established.
9. Answer in the same language as the user.

Structure the response with concise sections for known facts, hypotheses, and next checks.
"""


class InfrastructureRoutingError(ValueError):
    """Raised when infrastructure triage routing output is invalid."""


@dataclass(frozen=True, slots=True)
class InfrastructureRouteDecision:
    route: InfrastructureRoute
    reason: str
    clarification: str | None
    use_docs: bool = False


@dataclass(frozen=True, slots=True)
class InfrastructureExecutionPlan:
    workers: tuple[str, ...]
    reason: str
    clarification: str | None = None


@dataclass(frozen=True, slots=True)
class InfrastructureWorkerExecutionRecord:
    index: int
    role: str
    tool_results_added: int = 0
    evidence_added: int = 0
    runtime_steps_added: int = 0
    answer_created: bool = False


@dataclass(frozen=True, slots=True)
class InfrastructureAgentTurnResult:
    decision: InfrastructureRouteDecision
    answer: AgentAnswer | None
    supervisor_plan: InfrastructureExecutionPlan
    worker_trace: tuple[InfrastructureWorkerExecutionRecord, ...]

    @property
    def needs_clarification(self) -> bool:
        return self.decision.route == "clarify"


class InfrastructureTroubleshooterAgent:
    """Triage service incidents strictly from user-provided observations."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        router_model: ChatModel | None = None,
        answer_model: ChatModel | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.router_model = router_model or self._build_model(
            temperature=0.0
        )
        self.answer_model = answer_model or self._build_model(
            temperature=self.settings.model_temperature
        )

    def handle(self, question: str) -> InfrastructureAgentTurnResult:
        normalized = question.strip()
        if not normalized:
            raise ValueError("question must not be empty")

        decision = route_infrastructure_question(
            normalized,
            self.router_model,
        )
        if decision.route == "clarify":
            return InfrastructureAgentTurnResult(
                decision=decision,
                answer=None,
                supervisor_plan=InfrastructureExecutionPlan(
                    workers=(),
                    reason=decision.reason,
                    clarification=decision.clarification,
                ),
                worker_trace=(),
            )

        answer_text = self.answer_model.complete(
            system_prompt=TRIAGE_ANSWER_SYSTEM_PROMPT,
            user_prompt=_build_triage_prompt(
                normalized,
                max_hypotheses=self.settings.incident_max_hypotheses,
                max_next_steps=self.settings.incident_max_next_steps,
            ),
        )
        answer = AgentAnswer(
            answer=answer_text,
            doc_sources=(),
            cited_doc_sources=(),
            doc_citation_indices=(),
            runtime_sources=(),
            cited_runtime_sources=(),
            runtime_citation_indices=(),
            docs_context_truncated=False,
            runtime_context_truncated=False,
        )
        return InfrastructureAgentTurnResult(
            decision=decision,
            answer=answer,
            supervisor_plan=InfrastructureExecutionPlan(
                workers=("triage", "diagnosis"),
                reason=decision.reason,
            ),
            worker_trace=(
                InfrastructureWorkerExecutionRecord(
                    index=1,
                    role="triage",
                ),
                InfrastructureWorkerExecutionRecord(
                    index=2,
                    role="diagnosis",
                    answer_created=True,
                ),
            ),
        )

    def _build_model(
        self,
        *,
        temperature: float,
    ) -> OpenAICompatibleChatClient:
        if (
            not self.settings.model_name.strip()
            or not self.settings.model_base_url.strip()
        ):
            raise ValueError(
                "MODEL_NAME and MODEL_BASE_URL must be configured"
            )
        return OpenAICompatibleChatClient(
            model=self.settings.model_name,
            base_url=self.settings.model_base_url,
            api_key=self.settings.model_api_key,
            timeout_seconds=self.settings.model_timeout_seconds,
            temperature=temperature,
            max_tokens=self.settings.model_max_tokens,
            max_retries=self.settings.model_max_retries,
            retry_backoff_seconds=(
                self.settings.model_retry_backoff_seconds
            ),
        )


def route_infrastructure_question(
    question: str,
    model: ChatModel,
) -> InfrastructureRouteDecision:
    normalized = question.strip()
    if not normalized:
        raise ValueError("question must not be empty")

    raw = model.complete(
        system_prompt=TRIAGE_ROUTER_SYSTEM_PROMPT,
        user_prompt=f"User incident report:\n{normalized}",
    )
    payload = _parse_json_object(raw)

    route_raw = str(payload.get("route") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    clarification_raw = payload.get("clarification")

    if route_raw not in {"triage", "clarify"}:
        raise InfrastructureRoutingError(
            f"Unsupported infrastructure route: {route_raw!r}"
        )
    if not reason:
        raise InfrastructureRoutingError(
            "Infrastructure route requires a non-empty reason"
        )

    clarification: str | None = None
    if clarification_raw is not None:
        if not isinstance(clarification_raw, str):
            raise InfrastructureRoutingError(
                "clarification must be a string or null"
            )
        clarification = clarification_raw.strip() or None

    route = cast(InfrastructureRoute, route_raw)
    if route == "clarify" and clarification is None:
        raise InfrastructureRoutingError(
            "clarify route requires a clarification question"
        )
    if route == "triage":
        clarification = None

    return InfrastructureRouteDecision(
        route=route,
        reason=reason,
        clarification=clarification,
    )


def _build_triage_prompt(
    question: str,
    *,
    max_hypotheses: int,
    max_next_steps: int,
) -> str:
    return (
        "Incident report from the user:\n"
        f"{question}\n\n"
        "Constraints:\n"
        f"- Use at most {max_hypotheses} hypotheses.\n"
        f"- Recommend at most {max_next_steps} next checks.\n"
        "- Do not claim any live observation that the user did not provide.\n"
        "- Keep facts, hypotheses, and next checks clearly separated."
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
        raise InfrastructureRoutingError(
            f"Infrastructure router returned invalid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise InfrastructureRoutingError(
            "Infrastructure router response must be a JSON object"
        )
    return payload
