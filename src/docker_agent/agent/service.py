from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from sqlalchemy.engine import Engine

from docker_agent.agent.answer import AgentAnswer, generate_agent_answer
from docker_agent.agent.evidence import RuntimeEvidenceContext, build_runtime_evidence
from docker_agent.agent.router import AgentRouteDecision, route_question
from docker_agent.agent.runtime import execute_runtime_plan
from docker_agent.config import Settings, get_settings
from docker_agent.db import check_database, create_db_engine
from docker_agent.observability import stage_timer
from docker_agent.rag.context import RagContext, build_rag_context
from docker_agent.rag.embeddings import BgeM3Embedder
from docker_agent.rag.llm import ChatModel, OpenAICompatibleChatClient
from docker_agent.rag.reranker import (
    BgeReranker,
    PairScorer,
    rerank_candidates,
)
from docker_agent.rag.store import (
    HybridSearchResult,
    KeywordSearchResult,
    extract_keyword_terms,
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
        embedder: BgeM3Embedder | None = None,
        reranker: PairScorer | None = None,
        docs_engine: Engine | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.router_model = router_model or self._build_model(temperature=0.0)
        self.answer_model = answer_model or self._build_model(
            temperature=self.settings.model_temperature
        )
        self.docker_tools = docker_tools or build_docker_tools(
            self.settings
        )
        self._embedder = embedder or BgeM3Embedder(
            model_name=self.settings.embedding_model,
            device=self.settings.embedding_device,
            cache_folder=self.settings.embedding_cache_dir,
            batch_size=self.settings.embedding_batch_size,
        )
        self._reranker = reranker or BgeReranker(
            model_name=self.settings.rerank_model,
            device=(
                self.settings.rerank_device
                or self.settings.embedding_device
            ),
            cache_dir=(
                self.settings.rerank_cache_dir
                or self.settings.embedding_cache_dir
            ),
            batch_size=self.settings.rerank_batch_size,
            max_length=self.settings.rerank_max_length,
            use_fp16=self.settings.rerank_use_fp16,
        )
        self._docs_engine = docs_engine or create_db_engine()
        self._docs_database_checked = False
        self._retrieval_lock = Lock()
        self.docs_retriever = docs_retriever or self._retrieve_docs

    def handle(self, question: str) -> AgentTurnResult:
        """Route, gather evidence, and answer one user question."""

        question = question.strip()
        if not question:
            raise ValueError("question must not be empty")

        fast_turn = _fast_conversation_turn(question)
        if fast_turn is not None:
            return fast_turn

        decision = route_question(question, self.router_model)
        if decision.route == "chat":
            return _conversation_turn(question, decision)
        if decision.route == "clarify":
            return AgentTurnResult(decision=decision, answer=None)

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
            require_doc_citation=decision.route == "docs_only",
            require_runtime_citation=decision.route == "runtime_tools",
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

    def warmup_retrieval(self) -> None:
        """Load retrieval dependencies before the first documentation query."""

        with self._retrieval_lock:
            if not self._docs_database_checked:
                with stage_timer("rag_database"):
                    check_database(self._docs_engine)
                self._docs_database_checked = True

            embedder_warmup = getattr(
                self._embedder,
                "warmup",
                None,
            )
            if (
                not bool(getattr(self._embedder, "is_loaded", True))
                and callable(embedder_warmup)
            ):
                with stage_timer("embedding_model_warmup"):
                    embedder_warmup()

            reranker_warmup = getattr(
                self._reranker,
                "warmup",
                None,
            )
            if (
                not bool(getattr(self._reranker, "is_loaded", True))
                and callable(reranker_warmup)
            ):
                with stage_timer("reranker_model_warmup"):
                    reranker_warmup()

    def _retrieve_docs(self, question: str) -> RagContext:
        # Embedding and reranker models are intentionally reused for the
        # lifetime of this Agent instance. Loading BGE models on every query
        # can add minutes of avoidable latency on local development machines.
        with self._retrieval_lock:
            if not self._docs_database_checked:
                with stage_timer("rag_database"):
                    check_database(self._docs_engine)
                self._docs_database_checked = True

            with stage_timer("keyword_retrieval"):
                keyword = search_keyword_chunks(
                    self._docs_engine,
                    question,
                    top_k=self.settings.retrieval_candidate_k,
                )
                comparison_keyword = _comparison_keyword_results(
                    self._docs_engine,
                    question,
                    initial_results=keyword,
                    top_k=self.settings.retrieval_candidate_k,
                )

            fast_keyword = comparison_keyword or keyword
            if _use_keyword_fast_path(question, fast_keyword):
                fast_results = _keyword_results_to_hybrid(
                    fast_keyword
                )
                with stage_timer("context_build"):
                    return build_rag_context(
                        fast_results,
                        max_sources=min(
                            4,
                            self.settings.rerank_top_k,
                        ),
                        max_chars=min(
                            7_000,
                            self.settings.rag_context_max_chars,
                        ),
                    )

            with stage_timer("embedding"):
                query_embedding = self._embedder.embed_query(question)

            with stage_timer("dense_retrieval"):
                dense = search_similar_chunks(
                    self._docs_engine,
                    query_embedding,
                    top_k=self.settings.retrieval_candidate_k,
                )

            with stage_timer("fusion"):
                rrf = reciprocal_rank_fusion(
                    dense,
                    keyword,
                    top_k=self.settings.retrieval_candidate_k,
                    rrf_k=self.settings.retrieval_rrf_k,
                    dense_weight=self.settings.retrieval_dense_weight,
                    keyword_weight=self.settings.retrieval_keyword_weight,
                )

            with stage_timer("rerank"):
                reranked = rerank_candidates(
                    question,
                    rrf,
                    self._reranker,
                    top_k=self.settings.rerank_top_k,
                )

            with stage_timer("context_build"):
                return build_rag_context(
                    reranked,
                    max_sources=self.settings.rerank_top_k,
                    max_chars=self.settings.rag_context_max_chars,
                )

    @staticmethod
    def _validate_required_citations(
        decision: AgentRouteDecision,
        answer: AgentAnswer,
    ) -> None:
        if decision.route == "docs_only" and not answer.doc_citation_indices:
            raise ValueError(
                "Model answer did not cite Docker documentation evidence"
            )
        if (
            decision.route == "runtime_tools"
            and not answer.runtime_citation_indices
        ):
            raise ValueError(
                "Model answer did not cite requested runtime evidence"
            )


_COMPARISON_RE = re.compile(
    r"(?P<left>[A-Za-z0-9_ ./-]{2,80}?)\s*"
    r"(?:和|与|vs\.?|versus)\s*"
    r"(?P<right>[A-Za-z0-9_ ./-]{2,80}?)\s*"
    r"(?:有什么区别|有何区别|区别|比较|compare|difference)",
    re.IGNORECASE,
)


def _comparison_concepts(question: str) -> tuple[str, str] | None:
    match = _COMPARISON_RE.search(question)
    if match is None:
        return None
    left = match.group("left").strip(" -./")
    right = match.group("right").strip(" -./")
    if not left or not right:
        return None
    return left, right


def _comparison_keyword_results(
    engine: Engine,
    question: str,
    *,
    initial_results: list[KeywordSearchResult],
    top_k: int,
) -> list[KeywordSearchResult] | None:
    """Ensure comparison questions retrieve evidence for both concepts."""

    concepts = _comparison_concepts(question)
    if concepts is None:
        return None

    per_concept: list[list[KeywordSearchResult]] = []
    for concept in concepts:
        results = search_keyword_chunks(
            engine,
            concept,
            top_k=max(2, min(top_k, 6)),
        )
        if not results:
            return None
        per_concept.append(results)

    merged: list[KeywordSearchResult] = []
    seen: set[str] = set()

    for results in per_concept:
        for item in results[:2]:
            if item.chunk_id in seen:
                continue
            seen.add(item.chunk_id)
            merged.append(item)

    for item in initial_results:
        if item.chunk_id in seen:
            continue
        seen.add(item.chunk_id)
        merged.append(item)
        if len(merged) >= top_k:
            break

    return merged


def _use_keyword_fast_path(
    question: str,
    results: list[KeywordSearchResult],
) -> bool:
    """Use lexical-only retrieval when the question has strong exact anchors."""

    terms = extract_keyword_terms(question)
    return len(terms) >= 2 and len(results) >= 2


def _keyword_results_to_hybrid(
    results: list[KeywordSearchResult],
) -> list[HybridSearchResult]:
    converted: list[HybridSearchResult] = []
    for rank, item in enumerate(results, start=1):
        converted.append(
            HybridSearchResult(
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                title=item.title,
                section_path=item.section_path,
                content=item.content,
                source_url=item.source_url,
                file_path=item.file_path,
                rrf_score=item.rank_score,
                dense_rank=None,
                keyword_rank=rank,
                dense_distance=None,
                keyword_score=item.rank_score,
                rerank_score=None,
            )
        )
    return converted


def _fast_conversation_turn(
    question: str,
) -> AgentTurnResult | None:
    normalized = question.strip()
    lowered = normalized.lower().strip(" .!?！？。")
    greeting_inputs = {
        "hi",
        "hello",
        "hey",
        "你好",
        "您好",
        "嗨",
    }
    intro_inputs = {
        "你是谁",
        "介绍一下你自己",
        "介绍一下自己",
        "简单介绍自己",
        "你能做什么",
        "你可以做什么",
        "who are you",
        "what can you do",
        "introduce yourself",
        "介绍一下这个平台",
        "介绍这个平台",
        "这个平台能做什么",
    }
    help_inputs = {
        "帮助",
        "使用方法",
        "怎么使用",
        "如何使用",
        "help",
        "how to use",
        "怎么使用这个平台",
        "如何使用这个平台",
    }

    if lowered in greeting_inputs:
        text = (
            "你好，我是 Docker 支持专家。你可以直接描述 Docker 文档、"
            "镜像/容器、Compose、运行状态或日志相关问题；如果问题涉及"
            "服务级故障，建议使用“智能编排”模式让平台自动选择专家。"
        )
    elif lowered in intro_inputs:
        if "平台" in lowered:
            text = (
                "这是一个 Docker 智能支持平台。它包含 Docker 支持与基础设施排障"
                "专家，可以根据问题自动路由，结合 Docker 官方文档、只读运行时"
                "诊断、跨专家转交和结果综合来协助排障。推荐新对话使用“智能编排”"
                "模式；跨专家处理前会先请求你的批准。"
            )
        else:
            text = (
                "我是 Docker 支持专家，主要负责 Docker 文档问答、配置与使用说明，"
                "以及安全的只读运行时诊断。对于当前容器状态、日志、资源占用等问题，"
                "我会在信息充分时使用只读工具；跨服务或基础设施问题可以交给平台的"
                "“智能编排”模式继续处理。"
            )
    elif lowered in help_inputs:
        text = (
            "使用时直接描述现象即可。建议包含容器或服务名称、错误信息、发生时间"
            "和你已经确认的事实。普通 Docker 问题可以直接问我；不确定该找哪个"
            "专家时，使用“智能编排”模式。页面顶部的“使用指南”还有完整说明。"
        )
    else:
        return None

    decision = AgentRouteDecision(
        route="chat",
        reason="轻量会话无需文档检索或运行时工具。",
        container_ref=None,
        tools=(),
        clarification=None,
        use_docs=False,
    )
    return _conversation_turn(normalized, decision, answer_text=text)


def _conversation_turn(
    question: str,
    decision: AgentRouteDecision,
    *,
    answer_text: str | None = None,
) -> AgentTurnResult:
    text = answer_text or (
        "我是 Docker 支持专家，可以帮助你处理 Docker 使用、文档说明和"
        "只读运行时诊断。请直接描述你想解决的问题。"
    )
    answer = AgentAnswer(
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
    return AgentTurnResult(decision=decision, answer=answer)