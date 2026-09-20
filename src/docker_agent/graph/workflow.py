from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from langgraph.graph import END, START, StateGraph

from docker_agent.agent.answer import generate_agent_answer_from_evidence
from docker_agent.agent.core_adapters import (
    rag_context_to_evidence_bundle,
    runtime_context_to_evidence_bundle,
)
from docker_agent.agent.evidence import RuntimeEvidenceContext
from docker_agent.agent.router import route_question
from docker_agent.core.state import AgentState
from docker_agent.graph.state import GraphState
from docker_agent.rag.context import RagContext
from docker_agent.rag.llm import ChatModel

RouteNode = Callable[[GraphState], dict[str, object]]
DocsRetriever = Callable[[str], RagContext]
RouteEdge = Literal["docs", "end"]


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
        answer=None,
    )


def _coerce_graph_state(result: dict[str, object]) -> GraphState:
    return GraphState(
        agent_state=result["agent_state"],
        decision=result["decision"],
        docs_context=result["docs_context"],
        runtime_context=result["runtime_context"],
        answer=result["answer"],
    )
