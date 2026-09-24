from __future__ import annotations

from dataclasses import dataclass

from docker_agent.agent.answer import AgentAnswer
from docker_agent.agent.dynamic_service import (
    DynamicAgentTurnResult,
    DynamicDockerSupportAgent,
)
from docker_agent.graph.state import GraphState
from docker_agent.graph.workflow import run_support_graph
from docker_agent.multi_agent.execution import WorkerExecutionRecord
from docker_agent.multi_agent.supervisor import SupervisorPlan


@dataclass(frozen=True, slots=True)
class ProductConversationDecision:
    route: str = "chat"
    reason: str = "product conversational fast path"
    clarification: str | None = None
    use_docs: bool = False


@dataclass(frozen=True, slots=True)
class ProductConversationPlan:
    workers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProductConversationTurnResult:
    decision: ProductConversationDecision
    answer: AgentAnswer
    supervisor_plan: ProductConversationPlan
    worker_trace: tuple[WorkerExecutionRecord, ...] = ()

    @property
    def needs_clarification(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class LangGraphAgentTurnResult(DynamicAgentTurnResult):
    """Agent turn plus the supervisor plan and compact worker execution trace."""

    supervisor_plan: SupervisorPlan
    worker_trace: tuple[WorkerExecutionRecord, ...]


class LangGraphDockerSupportAgent(DynamicDockerSupportAgent):
    """Compatibility service backed by the unified coarse LangGraph workflow."""

    def handle_graph(self, question: str) -> GraphState:
        """Run one graph turn and expose the final GraphState for evaluation."""

        normalized = question.strip()
        if not normalized:
            raise ValueError("question must not be empty")

        return run_support_graph(
            normalized,
            router_model=self.router_model,
            planner_model=self.planner_model,
            answer_model=self.answer_model,
            docker_tools=self.docker_tools,
            docs_retriever=self.docs_retriever,
            max_steps=self.settings.dynamic_runtime_max_steps,
            evidence_max_chars=self.settings.runtime_evidence_max_chars,
        )

    def handle(
        self,
        question: str,
    ) -> LangGraphAgentTurnResult | ProductConversationTurnResult:
        """Handle product chat while preserving the technical LangGraph path."""

        normalized = question.strip()
        if not normalized:
            raise ValueError("question must not be empty")

        product_reply = _product_conversation_reply(normalized)
        if product_reply is not None:
            return ProductConversationTurnResult(
                decision=ProductConversationDecision(),
                answer=_product_conversation_answer(product_reply),
                supervisor_plan=ProductConversationPlan(),
            )

        state = self.handle_graph(normalized)
        decision = state["decision"]
        supervisor_plan = state["supervisor_plan"]
        if decision is None:
            raise ValueError("graph completed without a route decision")
        if supervisor_plan is None:
            raise ValueError("graph completed without a supervisor plan")

        return LangGraphAgentTurnResult(
            decision=decision,
            answer=state["answer"],
            runtime_trace=state["runtime_trace"],
            supervisor_plan=supervisor_plan,
            worker_trace=state["worker_trace"],
        )



def _product_conversation_answer(text: str) -> AgentAnswer:
    return AgentAnswer(
        answer=text,
        doc_sources=(),
        cited_doc_sources=(),
        doc_citation_indices=(),
        runtime_sources=(),
        cited_runtime_sources=(),
        runtime_citation_indices=(),
        docs_context_truncated=False,
        runtime_context_truncated=False,
    )


def _product_conversation_reply(question: str) -> str | None:
    normalized = " ".join(question.strip().split())
    lowered = normalized.lower()
    greetings = {
        "hi",
        "hello",
        "hey",
        "你好",
        "您好",
        "嗨",
        "哈喽",
    }
    if lowered in greetings:
        if any("\u4e00" <= char <= "\u9fff" for char in normalized):
            return (
                "你好，我是 Docker 智能支持平台中的 Docker 支持专家。"
                "你可以直接描述 Docker 文档、容器运行状态、日志、资源占用"
                "或故障现象，我会根据问题选择文档检索或只读诊断。"
            )
        return (
            "Hello! I am the Docker Support specialist in this platform. "
            "Ask me about Docker documentation, container runtime state, "
            "logs, resource usage, or troubleshooting."
        )

    compact = lowered.replace(" ", "")
    meta_queries = {
        "介绍自己",
        "简单介绍自己",
        "你是谁",
        "你能做什么",
        "你会什么",
        "怎么使用你",
        "如何使用你",
        "帮助",
        "help",
        "whatareyou",
        "whatcanyoudo",
    }
    if compact not in meta_queries:
        return None

    if any("\u4e00" <= char <= "\u9fff" for char in normalized):
        return (
            "我是 Docker 支持专家，主要负责三类任务：\n\n"
            "- **Docker 文档问答**：概念、配置、命令和最佳实践。\n"
            "- **运行时诊断**：在允许的只读工具范围内查看容器状态、日志和资源使用。\n"
            "- **故障排查**：根据已获得的证据区分已知事实、可能原因和下一步检查。\n\n"
            "如果问题已经超出单个 Docker 容器范围，建议切换到“智能编排”模式，"
            "系统可以把问题安全转交给基础设施排障专家。"
        )

    return (
        "I am the Docker Support specialist. I can answer Docker documentation "
        "questions, inspect allowed read-only runtime evidence, and help "
        "troubleshoot container issues. For broader service incidents, use "
        "Auto Orchestration so the platform can hand off to another specialist."
    )
