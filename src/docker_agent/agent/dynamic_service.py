from __future__ import annotations

from dataclasses import dataclass

from docker_agent.agent.answer import (
    AgentAnswer,
    generate_agent_answer,
    generate_general_support_answer,
)
from docker_agent.agent.dynamic_workflow import (
    DynamicRuntimeStep,
    run_dynamic_runtime_workflow,
)
from docker_agent.agent.evidence import RuntimeEvidenceContext
from docker_agent.agent.router import AgentRouteDecision, route_question
from docker_agent.agent.service import DockerSupportAgent
from docker_agent.rag.context import RagContext
from docker_agent.rag.llm import ChatModel


@dataclass(frozen=True, slots=True)
class DynamicAgentTurnResult:
    """One dynamic agent turn plus its runtime decision trace."""

    decision: AgentRouteDecision
    answer: AgentAnswer | None
    runtime_trace: tuple[DynamicRuntimeStep, ...]

    @property
    def needs_clarification(self) -> bool:
        return self.decision.route == "clarify"


class DynamicDockerSupportAgent(DockerSupportAgent):
    """Docker support agent that chooses runtime tools one observation at a time."""

    def __init__(
        self,
        *,
        planner_model: ChatModel | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.planner_model = planner_model or self._build_model(temperature=0.0)

    def handle(self, question: str) -> DynamicAgentTurnResult:
        question = question.strip()
        if not question:
            raise ValueError("question must not be empty")

        decision = route_question(question, self.router_model)
        if decision.route == "clarify":
            return DynamicAgentTurnResult(
                decision=decision,
                answer=None,
                runtime_trace=(),
            )
        if decision.route == "general_chat":
            return DynamicAgentTurnResult(
                decision=decision,
                answer=generate_general_support_answer(
                    question,
                    self.answer_model,
                ),
                runtime_trace=(),
            )

        runtime_context = RuntimeEvidenceContext(
            text="",
            sources=(),
            truncated=False,
        )
        runtime_trace: tuple[DynamicRuntimeStep, ...] = ()

        if decision.route == "runtime_tools":
            dynamic = run_dynamic_runtime_workflow(
                question=question,
                route=decision,
                planner_model=self.planner_model,
                docker_tools=self.docker_tools,
                max_steps=self.settings.dynamic_runtime_max_steps,
                evidence_max_chars=self.settings.runtime_evidence_max_chars,
            )
            runtime_context = dynamic.evidence
            runtime_trace = dynamic.trace

        docs_context = RagContext(text="", sources=(), truncated=False)
        if decision.use_docs:
            docs_context = self.docs_retriever(question)

        answer = generate_agent_answer(
            question,
            docs_context,
            runtime_context,
            self.answer_model,
        )
        self._validate_required_citations(decision, answer)

        return DynamicAgentTurnResult(
            decision=decision,
            answer=answer,
            runtime_trace=runtime_trace,
        )
