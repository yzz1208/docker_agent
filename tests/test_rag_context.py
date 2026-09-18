from docker_agent.rag.context import build_rag_context
from docker_agent.rag.store import HybridSearchResult


def _candidate(chunk_id: str, content: str) -> HybridSearchResult:
    return HybridSearchResult(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        title=f"Title {chunk_id}",
        section_path=["Root", f"Section {chunk_id}"],
        content=content,
        source_url=f"https://docs.docker.com/{chunk_id}/",
        file_path=f"{chunk_id}.md",
        rrf_score=0.1,
        dense_rank=1,
        keyword_rank=1,
        dense_distance=0.2,
        keyword_score=0.8,
        rerank_score=0.9,
    )


def test_build_rag_context_assigns_stable_citation_numbers() -> None:
    context = build_rag_context(
        [_candidate("a", "Alpha"), _candidate("b", "Beta")],
        max_sources=2,
        max_chars=2_000,
    )

    assert "[1]" in context.text
    assert "[2]" in context.text
    assert "Title: Title a" in context.text
    assert context.sources[0].index == 1
    assert context.sources[1].source_url.endswith("/b/")
    assert context.truncated is False


def test_build_rag_context_deduplicates_chunks() -> None:
    candidate = _candidate("a", "Alpha")
    context = build_rag_context([candidate, candidate], max_sources=5, max_chars=2_000)

    assert len(context.sources) == 1
    assert context.text.count("[1]") == 1


def test_build_rag_context_truncates_content_to_budget() -> None:
    context = build_rag_context(
        [_candidate("a", "x" * 2_000)],
        max_sources=1,
        max_chars=300,
    )

    assert len(context.text) <= 300
    assert len(context.sources) == 1
    assert context.truncated is True
