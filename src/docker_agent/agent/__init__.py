"""Routing and orchestration primitives for the Docker support agent."""

from docker_agent.agent.conversation import AgentConversation, ConversationState
from docker_agent.agent.dynamic_service import (
    DynamicAgentTurnResult,
    DynamicDockerSupportAgent,
)
from docker_agent.agent.router import AgentRouteDecision, route_question
from docker_agent.agent.runtime import execute_runtime_plan
from docker_agent.agent.service import AgentTurnResult, DockerSupportAgent

__all__ = [
    "AgentConversation",
    "AgentRouteDecision",
    "AgentTurnResult",
    "ConversationState",
    "DockerSupportAgent",
    "DynamicAgentTurnResult",
    "DynamicDockerSupportAgent",
    "execute_runtime_plan",
    "route_question",
]
