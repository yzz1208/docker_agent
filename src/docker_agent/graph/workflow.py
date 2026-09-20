from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from langgraph.graph import END, START, StateGraph

from docker_agent.agent.answer import generate_agent_answer_from_evidence
from docker_agent.agent.core_adapters import (
    dynamic_trace_to_agent_steps,
    rag_context_to_evidence_bundle,
    runtime_context_to_evidence_bundle,
)
from docker_agent.agent.evidence import RuntimeEvidenceContext
from docker_agent.agent.router import route_question
from docker_agent.core.state import AgentState
from docker_agent.core.tool_result import from_docker_tool_result
from docker_agent.graph.runtime_loop import run_runtime_loop_graph
from docker_agent.graph.state import GraphState
from docker_agent.rag.context import RagContext
from docker_agent.rag.llm import ChatModel
from docker_agent.tools.docker_cli import DockerReadOnlyTools

RouteNode = Callable[[GraphState], dict[str, object]]
DocsRetriever = Callable[[str], RagContext]
RouteEdge = Literal["docs", "runtime", "answer", "end"]


def build_route_graph(router_model: ChatModel):
    """Compile the minimal Phase 2 graph: START -> route -> END."""

    def route_node(state: GraphState) -> dict[str, object]:
        current = state["agent_state"]
        decision = route_question(current.question, router_model)
        updated = current.with_route(
            decision.route,
            container_ref=decision.container_ref,
            use_docs=decision.use_docs,
        )
        return {
            "agent_state": updated,
            "decision": decision,
        }

    builder = StateGraph(GraphState)
    builder.add_node("route", route_node)
    builder.add_edge(START, "route")
    builder.add_edge("route", END)
    return builder.compile()


def run_route_graph(question: str, router_model: ChatModel) -> GraphState:
    """Run the minimal graph for one question and return its final state."""

    normalized = question.strip()
    if not normalized:
        raise ValueError("question must not be empty")

    graph = build_route_graph(router_model)
    result = graph.invoke(_initial_graph_state(normalized))
    return _coerce_graph_state(result)



def build_docs_only_graph(
    *,
    router_model: ChatModel,
    answer_model: ChatModel,
    docs_retriever: DocsRetriever,
):
    """Compile Phase 2 Step 2: route -> docs -> answer for docs-only requests."""

    def route_node(state: GraphState) -> dict[str, object]:
        current = state["agent_state"]
        decision = route_question(current.question, router_model)
        updated = current.with_route(
            decision.route,
            container_ref=decision.container_ref,
            use_docs=decision.use_docs,
        )
        return {
            "agent_state": updated,
            "decision": decision,
        }

    def route_edge(state: GraphState) -> RouteEdge:
        decision = state["decision"]
        if decision is None:
            raise ValueError("route decision is missing")
        if decision.route == "docs_only":
            return "docs"
        return "end"

    def docs_node(state: GraphState) -> dict[str, object]:
        current = state["agent_state"]
        docs_context = docs_retriever(current.question)
        docs_bundle = rag_context_to_evidence_bundle(docs_context)

        updated = current
        for item in docs_bundle.items:
            updated = updated.append_evidence(item)

        return {
            "agent_state": updated,
            "docs_context": docs_context,
        }

    def answer_node(state: GraphState) -> dict[str, object]:
        current = state["agent_state"]
        decision = state["decision"]
        docs_context = state["docs_context"]
        runtime_context = state["runtime_context"]

        if decision is None:
            raise ValueError("route decision is missing")
        if docs_context is None:
            raise ValueError("docs context is missing")
        if runtime_context is None:
            raise ValueError("runtime context is missing")

        answer = generate_agent_answer_from_evidence(
            current.question,
            rag_context_to_evidence_bundle(docs_context),
            runtime_context_to_evidence_bundle(runtime_context),
            answer_model,
            doc_sources=docs_context.sources,
            runtime_sources=runtime_context.sources,
        )
        if decision.route == "docs_only" and not answer.doc_citation_indices:
            raise ValueError("Model answer did not cite Docker documentation evidence")

        return {
            "agent_state": current.with_answer(answer.answer),
            "answer": answer,
        }

    builder = StateGraph(GraphState)
    builder.add_node("route", route_node)
    builder.add_node("docs", docs_node)
    builder.add_node("answer", answer_node)

    builder.add_edge(START, "route")
    builder.add_conditional_edges(
        "route",
        route_edge,
        {
            "docs": "docs",
            "end": END,
        },
    )
    builder.add_edge("docs", "answer")
    builder.add_edge("answer", END)
    return builder.compile()


def run_docs_only_graph(
    question: str,
    *,
    router_model: ChatModel,
    answer_model: ChatModel,
    docs_retriever: DocsRetriever,
) -> GraphState:
    """Run the Step 2 graph and return the final orchestration state."""

    normalized = question.strip()
    if not normalized:
        raise ValueError("question must not be empty")

    graph = build_docs_only_graph(
        router_model=router_model,
        answer_model=answer_model,
        docs_retriever=docs_retriever,
    )
    result = graph.invoke(_initial_graph_state(normalized))
    return _coerce_graph_state(result)


def _initial_graph_state(question: str) -> GraphState:
    return GraphState(
        agent_state=AgentState(question=question),
        decision=None,
        docs_context=None,
        runtime_context=RuntimeEvidenceContext(
            text="",
            sources=(),
            truncated=False,
        ),
        runtime_trace=(),
        answer=None,
    )


def _coerce_graph_state(result: dict[str, object]) -> GraphState:
    return GraphState(
        agent_state=result["agent_state"],
        decision=result["decision"],
        docs_context=result["docs_context"],
        runtime_context=result["runtime_context"],
        runtime_trace=result["runtime_trace"],
        answer=result["answer"],
    )



def build_runtime_graph(
    *,
    router_model: ChatModel,
    planner_model: ChatModel,
    answer_model: ChatModel,
    docker_tools: DockerReadOnlyTools,
    max_steps: int = 4,
    evidence_max_chars: int = 8_000,
):
    """Compile Phase 2 Step 3: route -> runtime(existing loop) -> answer."""

    def route_node(state: GraphState) -> dict[str, object]:
        current = state["agent_state"]
        decision = route_question(current.question, router_model)
        updated = current.with_route(
            decision.route,
            container_ref=decision.container_ref,
            use_docs=decision.use_docs,
        )
        return {
            "agent_state": updated,
            "decision": decision,
        }

    def route_edge(state: GraphState) -> RouteEdge:
        decision = state["decision"]
        if decision is None:
            raise ValueError("route decision is missing")
        if decision.route == "runtime_tools" and not decision.use_docs:
            return "runtime"
        return "end"

    def runtime_node(state: GraphState) -> dict[str, object]:
        current = state["agent_state"]
        decision = state["decision"]
        if decision is None:
            raise ValueError("route decision is missing")
        if decision.route != "runtime_tools":
            raise ValueError("runtime node requires runtime_tools route")

        dynamic = run_runtime_loop_graph(
            question=current.question,
            route=decision,
            planner_model=planner_model,
            docker_tools=docker_tools,
            max_steps=max_steps,
            evidence_max_chars=evidence_max_chars,
        )

        updated = current
        for result in dynamic.results:
            updated = updated.append_tool_result(
                from_docker_tool_result(result)
            )
        for item in runtime_context_to_evidence_bundle(dynamic.evidence).items:
            updated = updated.append_evidence(item)
        for step in dynamic_trace_to_agent_steps(dynamic.trace):
            updated = updated.append_runtime_step(step)

        return {
            "agent_state": updated,
            "runtime_context": dynamic.evidence,
            "runtime_trace": dynamic.trace,
        }

    def answer_node(state: GraphState) -> dict[str, object]:
        current = state["agent_state"]
        decision = state["decision"]
        runtime_context = state["runtime_context"]

        if decision is None:
            raise ValueError("route decision is missing")
        if runtime_context is None:
            raise ValueError("runtime context is missing")

        docs_context = RagContext(
            text="",
            sources=(),
            truncated=False,
        )
        answer = generate_agent_answer_from_evidence(
            current.question,
            rag_context_to_evidence_bundle(docs_context),
            runtime_context_to_evidence_bundle(runtime_context),
            answer_model,
            doc_sources=(),
            runtime_sources=runtime_context.sources,
        )
        if not answer.runtime_citation_indices:
            raise ValueError("Model answer did not cite requested runtime evidence")

        return {
            "agent_state": current.with_answer(answer.answer),
            "answer": answer,
        }

    builder = StateGraph(GraphState)
    builder.add_node("route", route_node)
    builder.add_node("runtime", runtime_node)
    builder.add_node("answer", answer_node)

    builder.add_edge(START, "route")
    builder.add_conditional_edges(
        "route",
        route_edge,
        {
            "runtime": "runtime",
            "end": END,
        },
    )
    builder.add_edge("runtime", "answer")
    builder.add_edge("answer", END)
    return builder.compile()


def run_runtime_graph(
    question: str,
    *,
    router_model: ChatModel,
    planner_model: ChatModel,
    answer_model: ChatModel,
    docker_tools: DockerReadOnlyTools,
    max_steps: int = 4,
    evidence_max_chars: int = 8_000,
) -> GraphState:
    """Run the Step 3 runtime coarse graph for one question."""

    normalized = question.strip()
    if not normalized:
        raise ValueError("question must not be empty")

    graph = build_runtime_graph(
        router_model=router_model,
        planner_model=planner_model,
        answer_model=answer_model,
        docker_tools=docker_tools,
        max_steps=max_steps,
        evidence_max_chars=evidence_max_chars,
    )
    result = graph.invoke(_initial_graph_state(normalized))
    return _coerce_graph_state(result)



def build_support_graph(
    *,
    router_model: ChatModel,
    planner_model: ChatModel,
    answer_model: ChatModel,
    docker_tools: DockerReadOnlyTools,
    docs_retriever: DocsRetriever,
    max_steps: int = 4,
    evidence_max_chars: int = 8_000,
):
    """Compile the Phase 2 Step 4 unified coarse-grained support graph."""

    def route_node(state: GraphState) -> dict[str, object]:
        current = state["agent_state"]
        decision = route_question(current.question, router_model)
        updated = current.with_route(
            decision.route,
            container_ref=decision.container_ref,
            use_docs=decision.use_docs,
        )
        return {
            "agent_state": updated,
            "decision": decision,
        }

    def route_edge(state: GraphState) -> RouteEdge:
        decision = state["decision"]
        if decision is None:
            raise ValueError("route decision is missing")
        if decision.route == "clarify":
            return "end"
        if decision.route == "docs_only":
            return "docs"
        if decision.route == "runtime_tools":
            return "runtime"
        raise ValueError(f"unsupported route: {decision.route}")

    def runtime_node(state: GraphState) -> dict[str, object]:
        current = state["agent_state"]
        decision = state["decision"]
        if decision is None:
            raise ValueError("route decision is missing")
        if decision.route != "runtime_tools":
            raise ValueError("runtime node requires runtime_tools route")

        dynamic = run_runtime_loop_graph(
            question=current.question,
            route=decision,
            planner_model=planner_model,
            docker_tools=docker_tools,
            max_steps=max_steps,
            evidence_max_chars=evidence_max_chars,
        )

        updated = current
        for result in dynamic.results:
            updated = updated.append_tool_result(
                from_docker_tool_result(result)
            )
        for item in runtime_context_to_evidence_bundle(dynamic.evidence).items:
            updated = updated.append_evidence(item)
        for step in dynamic_trace_to_agent_steps(dynamic.trace):
            updated = updated.append_runtime_step(step)

        return {
            "agent_state": updated,
            "runtime_context": dynamic.evidence,
            "runtime_trace": dynamic.trace,
        }

    def after_runtime_edge(state: GraphState) -> RouteEdge:
        decision = state["decision"]
        if decision is None:
            raise ValueError("route decision is missing")
        return "docs" if decision.use_docs else "answer"

    def docs_node(state: GraphState) -> dict[str, object]:
        current = state["agent_state"]
        docs_context = docs_retriever(current.question)
        docs_bundle = rag_context_to_evidence_bundle(docs_context)

        updated = current
        for item in docs_bundle.items:
            updated = updated.append_evidence(item)

        return {
            "agent_state": updated,
            "docs_context": docs_context,
        }

    def answer_node(state: GraphState) -> dict[str, object]:
        current = state["agent_state"]
        decision = state["decision"]
        if decision is None:
            raise ValueError("route decision is missing")

        docs_context = state["docs_context"] or RagContext(
            text="",
            sources=(),
            truncated=False,
        )
        runtime_context = state["runtime_context"]
        if runtime_context is None:
            raise ValueError("runtime context is missing")

        answer = generate_agent_answer_from_evidence(
            current.question,
            rag_context_to_evidence_bundle(docs_context),
            runtime_context_to_evidence_bundle(runtime_context),
            answer_model,
            doc_sources=docs_context.sources,
            runtime_sources=runtime_context.sources,
        )

        if decision.route == "docs_only" and not answer.doc_citation_indices:
            raise ValueError("Model answer did not cite Docker documentation evidence")
        if decision.route == "runtime_tools" and not answer.runtime_citation_indices:
            raise ValueError("Model answer did not cite requested runtime evidence")

        return {
            "agent_state": current.with_answer(answer.answer),
            "answer": answer,
        }

    builder = StateGraph(GraphState)
    builder.add_node("route", route_node)
    builder.add_node("runtime", runtime_node)
    builder.add_node("docs", docs_node)
    builder.add_node("answer", answer_node)

    builder.add_edge(START, "route")
    builder.add_conditional_edges(
        "route",
        route_edge,
        {
            "docs": "docs",
            "runtime": "runtime",
            "end": END,
        },
    )
    builder.add_conditional_edges(
        "runtime",
        after_runtime_edge,
        {
            "docs": "docs",
            "answer": "answer",
        },
    )
    builder.add_edge("docs", "answer")
    builder.add_edge("answer", END)
    return builder.compile()


def run_support_graph(
    question: str,
    *,
    router_model: ChatModel,
    planner_model: ChatModel,
    answer_model: ChatModel,
    docker_tools: DockerReadOnlyTools,
    docs_retriever: DocsRetriever,
    max_steps: int = 4,
    evidence_max_chars: int = 8_000,
) -> GraphState:
    """Run the unified coarse-grained support graph for one question."""

    normalized = question.strip()
    if not normalized:
        raise ValueError("question must not be empty")

    graph = build_support_graph(
        router_model=router_model,
        planner_model=planner_model,
        answer_model=answer_model,
        docker_tools=docker_tools,
        docs_retriever=docs_retriever,
        max_steps=max_steps,
        evidence_max_chars=evidence_max_chars,
    )
    result = graph.invoke(_initial_graph_state(normalized))
    return _coerce_graph_state(result)
