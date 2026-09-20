from __future__ import annotations

from collections.abc import Callable

from langgraph.graph import END, START, StateGraph

from docker_agent.agent.router import route_question
from docker_agent.core.state import AgentState
from docker_agent.graph.state import GraphState
from docker_agent.rag.llm import ChatModel

RouteNode = Callable[[GraphState], dict[str, object]]


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
    result = graph.invoke(
        {
            "agent_state": AgentState(question=normalized),
            "decision": None,
        }
    )
    return GraphState(
        agent_state=result["agent_state"],
        decision=result["decision"],
    )
