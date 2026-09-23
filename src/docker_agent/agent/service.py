from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from sqlalchemy.engine import Engine

from docker_agent.agent.answer import (
    AgentAnswer,
    generate_agent_answer,
    generate_general_support_answer,
)
from docker_agent.agent.evidence import RuntimeEvidenceContext, build_runtime_evidence
from docker_agent.agent.router import AgentRouteDecision, route_question
from docker_agent.agent.runtime import execute_runtime_plan
from docker_agent.config import Settings, get_settings
from docker_agent.db import check_database, create_db_engine
from docker_agent.rag.context import RagContext, build_rag_context
from docker_agent.rag.embeddings import BgeM3Embedder
from docker_agent.rag.llm import ChatModel, OpenAICompatibleChatClient
from docker_agent.rag.reranker import BgeReranker, PairScorer, rerank_candidates
from docker_agent.rag.store import (
    reciprocal_rank_fusion,
    search_keyword_chunks,
    search_similar_chunks,
)
from docker_agent.tools.docker_cli import (
    DockerReadOnlyTools,
    build_docker_tools,
)

DocsRetriever = Callable[[str], RagContext]


@dataclass(frozen=True, slots=True)
class AgentTurnResult:
    """One completed agent turn or one clarification request."""

    decision: AgentRouteDecision
    answer: AgentAnswer | None

    @property
    def needs_clarification(self) -> bool:
        return self.decision.route == "clarify"


class DockerSupportAgent:
    """Single-turn orchestration for docs RAG and read-only Docker diagnostics."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        router_model: ChatModel | None = None,
        answer_model: ChatModel | None = None,
        docker_tools: DockerReadOnlyTools | None = None,
        docs_retriever: DocsRetriever | None = None,
        docs_engine: Engine | None = None,
        embedder: BgeM3Embedder | None = None,
        reranker: PairScorer | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.router_model = router_model or self._build_model(temperature=0.0)
        self.answer_model = answer_model or self._build_model(
            temperature=self.settings.model_temperature
        )
        self.docker_tools = docker_tools or build_docker_tools(
            self.settings
        )
        self.docs_retriever = docs_retriever or self._retrieve_docs
        self._docs_engine = docs_engine
        self._embedder = embedder
        self._reranker = reranker
        self._docs_resource_lock = Lock()

    def handle(self, question: str) -> AgentTurnResult:
        """Route, gather evidence, and answer one user question."""

        question = question.strip()
        if not question:
            raise ValueError("question must not be empty")

        decision = route_question(question, self.router_model)
        if decision.route == "clarify":
            return AgentTurnResult(decision=decision, answer=None)
        if decision.route == "general_chat":
            return AgentTurnResult(
                decision=decision,
                answer=generate_general_support_answer(
                    question,
                    self.answer_model,
                ),
            )

        runtime_context = RuntimeEvidenceContext(
            text="",
            sources=(),
            truncated=False,
        )
        if decision.route == "runtime_tools":
            runtime_results = execute_runtime_plan(decision, self.docker_tools)
            runtime_context = build_runtime_evidence(
                runtime_results,
                max_chars=self.settings.runtime_evidence_max_chars,
            )

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
        return AgentTurnResult(decision=decision, answer=answer)

    def _build_model(self, *, temperature: float) -> OpenAICompatibleChatClient:
        if not self.settings.model_name.strip() or not self.settings.model_base_url.strip():
            raise ValueError("MODEL_NAME and MODEL_BASE_URL must be configured")
        return OpenAICompatibleChatClient(
            model=self.settings.model_name,
            base_url=self.settings.model_base_url,
            api_key=self.settings.model_api_key,
            timeout_seconds=self.settings.model_timeout_seconds,
            temperature=temperature,
            max_tokens=self.settings.model_max_tokens,
            max_retries=self.settings.model_max_retries,
            retry_backoff_seconds=self.settings.model_retry_backoff_seconds,
        )

    def _retrieve_docs(self, question: str) -> RagContext:
        engine = self._get_docs_engine()
        embedder = self._get_embedder()
        query_embedding = embedder.embed_query(question)
        dense = search_similar_chunks(
            engine,
            query_embedding,
            top_k=self.settings.retrieval_candidate_k,
        )
        keyword = search_keyword_chunks(
            engine,
            question,
            top_k=self.settings.retrieval_candidate_k,
        )
        rrf = reciprocal_rank_fusion(
            dense,
            keyword,
            top_k=self.settings.retrieval_candidate_k,
            rrf_k=self.settings.retrieval_rrf_k,
            dense_weight=self.settings.retrieval_dense_weight,
            keyword_weight=self.settings.retrieval_keyword_weight,
        )

        reranked = rerank_candidates(
            question,
            rrf,
            self._get_reranker(),
            top_k=self.settings.rerank_top_k,
        )
        return build_rag_context(
            reranked,
            max_sources=self.settings.rerank_top_k,
            max_chars=self.settings.rag_context_max_chars,
        )

    def _get_docs_engine(self) -> Engine:
        if self._docs_engine is not None:
            return self._docs_engine
        with self._docs_resource_lock:
            if self._docs_engine is None:
                engine = create_db_engine()
                check_database(engine)
                self._docs_engine = engine
        return self._docs_engine

    def _get_embedder(self) -> BgeM3Embedder:
        if self._embedder is not None:
            return self._embedder
        with self._docs_resource_lock:
            if self._embedder is None:
                self._embedder = BgeM3Embedder()
        return self._embedder

    def _get_reranker(self) -> PairScorer:
        if self._reranker is not None:
            return self._reranker
        with self._docs_resource_lock:
            if self._reranker is None:
                self._reranker = BgeReranker()
        return self._reranker

    @staticmethod
    def _validate_required_citations(
        decision: AgentRouteDecision,
        answer: AgentAnswer,
    ) -> None:
        if decision.route == "docs_only" and not answer.doc_citation_indices:
            raise ValueError("Model answer did not cite Docker documentation evidence")
        if decision.route == "runtime_tools" and not answer.runtime_citation_indices:
            raise ValueError("Model answer did not cite requested runtime evidence")
