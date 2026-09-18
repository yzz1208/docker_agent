from __future__ import annotations

import argparse
import gc

from sqlalchemy.exc import SQLAlchemyError

from docker_agent.agent.answer import generate_agent_answer
from docker_agent.agent.evidence import RuntimeEvidenceContext, build_runtime_evidence
from docker_agent.agent.router import AgentRoutingError, route_question
from docker_agent.agent.runtime import execute_runtime_plan
from docker_agent.config import get_settings
from docker_agent.db import check_database, create_db_engine
from docker_agent.rag.answer import CitationValidationError
from docker_agent.rag.context import RagContext, build_rag_context
from docker_agent.rag.embeddings import BgeM3Embedder
from docker_agent.rag.llm import OpenAICompatibleChatClient
from docker_agent.rag.reranker import BgeReranker, rerank_candidates
from docker_agent.rag.store import (
    reciprocal_rank_fusion,
    search_keyword_chunks,
    search_similar_chunks,
)
from docker_agent.tools.docker_cli import DockerReadOnlyTools, DockerToolTimeout


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Docker support agent with docs and read-only runtime evidence."
    )
    parser.add_argument("question")
    return parser.parse_args()


def _model(*, temperature: float) -> OpenAICompatibleChatClient:
    settings = get_settings()
    return OpenAICompatibleChatClient(
        model=settings.model_name,
        base_url=settings.model_base_url,
        api_key=settings.model_api_key,
        timeout_seconds=settings.model_timeout_seconds,
        temperature=temperature,
    )


def _release_cuda_cache() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _retrieve_docs(question: str) -> RagContext:
    settings = get_settings()
    engine = create_db_engine()
    check_database(engine)

    embedder = BgeM3Embedder()
    query_embedding = embedder.embed_query(question)
    dense = search_similar_chunks(
        engine,
        query_embedding,
        top_k=settings.retrieval_candidate_k,
    )
    keyword = search_keyword_chunks(
        engine,
        question,
        top_k=settings.retrieval_candidate_k,
    )
    rrf = reciprocal_rank_fusion(
        dense,
        keyword,
        top_k=settings.retrieval_candidate_k,
        rrf_k=settings.retrieval_rrf_k,
        dense_weight=settings.retrieval_dense_weight,
        keyword_weight=settings.retrieval_keyword_weight,
    )

    del embedder
    _release_cuda_cache()

    reranker = BgeReranker()
    reranked = rerank_candidates(
        question,
        rrf,
        reranker,
        top_k=settings.rerank_top_k,
    )
    return build_rag_context(
        reranked,
        max_sources=settings.rerank_top_k,
        max_chars=settings.rag_context_max_chars,
    )


def main() -> None:
    args = parse_args()
    question = args.question.strip()
    if not question:
        raise SystemExit("question must not be empty")

    settings = get_settings()
    if not settings.model_name.strip() or not settings.model_base_url.strip():
        raise SystemExit("MODEL_NAME and MODEL_BASE_URL must be configured in .env")

    router_model = _model(temperature=0.0)
    try:
        decision = route_question(question, router_model)
    except AgentRoutingError as exc:
        raise SystemExit(f"Unsafe/invalid route decision: {exc}") from None

    print(f"Route: {decision.route}")
    print(f"Reason: {decision.reason}")
    print(f"Use docs: {decision.use_docs}")

    if decision.route == "clarify":
        print(f"\n{decision.clarification}")
        return

    runtime_context = RuntimeEvidenceContext(text="", sources=(), truncated=False)
    if decision.route == "runtime_tools":
        docker_tools = DockerReadOnlyTools(
            timeout_seconds=settings.docker_tool_timeout_seconds,
            max_log_lines=settings.docker_logs_max_lines,
        )
        try:
            runtime_results = execute_runtime_plan(decision, docker_tools)
        except (ValueError, DockerToolTimeout) as exc:
            raise SystemExit(str(exc)) from None

        runtime_context = build_runtime_evidence(
            runtime_results,
            max_chars=settings.runtime_evidence_max_chars,
        )

    docs_context = RagContext(text="", sources=(), truncated=False)
    if decision.use_docs:
        try:
            docs_context = _retrieve_docs(question)
        except SQLAlchemyError:
            if decision.route == "docs_only":
                raise SystemExit(
                    "PostgreSQL is unavailable. Start Docker Desktop and run "
                    "docker compose up -d postgres, then retry."
                ) from None

    answer_model = _model(temperature=settings.model_temperature)
    try:
        result = generate_agent_answer(
            question,
            docs_context,
            runtime_context,
            answer_model,
        )
    except CitationValidationError as exc:
        raise SystemExit(f"Invalid model citation: {exc}") from None

    if decision.route == "docs_only" and not result.doc_citation_indices:
        raise SystemExit("Model answer did not cite Docker documentation evidence.")
    if decision.route == "runtime_tools" and not result.runtime_citation_indices:
        raise SystemExit("Model answer did not cite the runtime evidence it requested.")

    print("\nAnswer\n")
    print(result.answer)

    if result.cited_runtime_sources:
        print("\nRuntime evidence")
        for source in result.cited_runtime_sources:
            command = " ".join(source.command)
            status = "success" if source.ok else "error"
            print(f"[R{source.index}] {source.tool} ({status})")
            print(f"    {command}")

    if result.cited_doc_sources:
        print("\nDocker Docs")
        for source in result.cited_doc_sources:
            section = f" > {source.section}" if source.section else ""
            print(f"[{source.index}] {source.title}{section}")
            print(f"    {source.source_url}")

    if result.docs_context_truncated or result.runtime_context_truncated:
        print("\nNote: one or more evidence contexts were truncated to configured limits.")


if __name__ == "__main__":
    main()
