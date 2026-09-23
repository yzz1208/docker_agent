from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from docker_agent.agent.answer import (
    AgentAnswer,
    generate_agent_answer_from_evidence,
    generate_general_support_answer,
)
from docker_agent.agent.core_adapters import (
    dynamic_trace_to_agent_steps,
    rag_context_to_evidence_bundle,
    runtime_context_to_evidence_bundle,
)
from docker_agent.agent.dynamic_workflow import DynamicRuntimeStep
from docker_agent.agent.evidence import RuntimeEvidenceContext
from docker_agent.agent.router import AgentRouteDecision
from docker_agent.core.state import AgentState
from docker_agent.core.tool_result import from_docker_tool_result
from docker_agent.graph.runtime_loop import run_runtime_loop_graph
from docker_agent.rag.context import RagContext
from docker_agent.rag.llm import ChatModel
from docker_agent.tools.docker_cli import DockerReadOnlyTools

DocsRetriever = Callable[[str], RagContext]


@dataclass(frozen=True, slots=True)
class KnowledgeWorkerResult:
    state: AgentState
    context: RagContext


@dataclass(frozen=True, slots=True)
class RuntimeWorkerResult:
    state: AgentState
    context: RuntimeEvidenceContext
    trace: tuple[DynamicRuntimeStep, ...]


@dataclass(frozen=True, slots=True)
class DiagnosisWorkerResult:
    state: AgentState
    answer: AgentAnswer


@dataclass(frozen=True, slots=True)
class KnowledgeWorker:
    """Retrieve Docker documentation and append normalized knowledge evidence."""

    docs_retriever: DocsRetriever

    def run(self, state: AgentState) -> KnowledgeWorkerResult:
        context = self.docs_retriever(state.question)
        bundle = rag_context_to_evidence_bundle(context)

        updated = state
        for item in bundle.items:
            updated = updated.append_evidence(item)

        return KnowledgeWorkerResult(
            state=updated,
            context=context,
        )


@dataclass(frozen=True, slots=True)
class RuntimeWorker:
    """Collect runtime evidence using the node-level LangGraph runtime loop."""

    planner_model: ChatModel
    docker_tools: DockerReadOnlyTools
    max_steps: int = 4
    evidence_max_chars: int = 8_000

    def __post_init__(self) -> None:
        if self.max_steps <= 0:
            raise ValueError("max_steps must be positive")
        if self.evidence_max_chars <= 0:
            raise ValueError("evidence_max_chars must be positive")

    def run(
        self,
        state: AgentState,
        decision: AgentRouteDecision,
    ) -> RuntimeWorkerResult:
        if decision.route != "runtime_tools":
            raise ValueError("RuntimeWorker requires runtime_tools route")

        dynamic = run_runtime_loop_graph(
            question=state.question,
            route=decision,
            planner_model=self.planner_model,
            docker_tools=self.docker_tools,
            max_steps=self.max_steps,
            evidence_max_chars=self.evidence_max_chars,
        )

        updated = state
        for result in dynamic.results:
            updated = updated.append_tool_result(from_docker_tool_result(result))
        for item in runtime_context_to_evidence_bundle(dynamic.evidence).items:
            updated = updated.append_evidence(item)
        for step in dynamic_trace_to_agent_steps(dynamic.trace):
            updated = updated.append_runtime_step(step)

        return RuntimeWorkerResult(
            state=updated,
            context=dynamic.evidence,
            trace=dynamic.trace,
        )


@dataclass(frozen=True, slots=True)
class DiagnosisWorker:
    """Synthesize the final evidence-grounded answer for one support turn."""

    answer_model: ChatModel

    def run(
        self,
        state: AgentState,
        decision: AgentRouteDecision,
        *,
        docs_context: RagContext | None = None,
        runtime_context: RuntimeEvidenceContext | None = None,
    ) -> DiagnosisWorkerResult:
        docs = docs_context or RagContext(
            text="",
            sources=(),
            truncated=False,
        )
        runtime = runtime_context or RuntimeEvidenceContext(
            text="",
            sources=(),
            truncated=False,
        )

        if decision.route == "general_chat":
            answer = generate_general_support_answer(
                state.question,
                self.answer_model,
            )
        else:
            answer = generate_agent_answer_from_evidence(
                state.question,
                rag_context_to_evidence_bundle(docs),
                runtime_context_to_evidence_bundle(runtime),
                self.answer_model,
                doc_sources=docs.sources,
                runtime_sources=runtime.sources,
            )

        if decision.route == "docs_only" and not answer.doc_citation_indices:
            raise ValueError(
                "DiagnosisWorker answer did not cite Docker documentation evidence"
            )
        if decision.route == "runtime_tools" and not answer.runtime_citation_indices:
            raise ValueError(
                "DiagnosisWorker answer did not cite requested runtime evidence"
            )

        return DiagnosisWorkerResult(
            state=state.with_answer(answer.answer),
            answer=answer,
        )
