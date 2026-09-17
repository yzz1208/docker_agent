from docker_agent.rag.store import (
    KeywordSearchResult,
    SearchResult,
    extract_keyword_terms,
    reciprocal_rank_fusion,
)


def _dense(chunk_id: str, distance: float = 0.2) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        title=chunk_id,
        section_path=[chunk_id],
        content="content",
        source_url="https://docs.docker.com/example/",
        file_path=f"{chunk_id}.md",
        distance=distance,
    )


def _keyword(chunk_id: str, score: float = 0.8) -> KeywordSearchResult:
    return KeywordSearchResult(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        title=chunk_id,
        section_path=[chunk_id],
        content="content",
        source_url="https://docs.docker.com/example/",
        file_path=f"{chunk_id}.md",
        rank_score=score,
    )


def test_extract_keyword_terms_keeps_technical_anchors() -> None:
    terms = extract_keyword_terms(
        "Docker Compose 里 DOCKER_HOST、env_file 和 iptables 报错，exit code 137"
    )

    assert "docker" not in terms
    assert "compose" in terms
    assert "docker_host" in terms
    assert "env_file" in terms
    assert "iptables" in terms
    assert "exit" in terms
    assert "code" in terms
    assert "137" in terms


def test_extract_keyword_terms_can_be_empty_for_chinese_only_query() -> None:
    assert extract_keyword_terms("容器删掉以后数据还要保留怎么办") == []


def test_rrf_promotes_chunk_present_in_both_rankings() -> None:
    dense = [_dense("dense-only"), _dense("shared", 0.25)]
    keyword = [_keyword("keyword-only"), _keyword("shared", 0.7)]

    fused = reciprocal_rank_fusion(dense, keyword, top_k=3, rrf_k=60)

    assert fused[0].chunk_id == "shared"
    assert fused[0].dense_rank == 2
    assert fused[0].keyword_rank == 2
    assert fused[1].chunk_id == "dense-only"
    assert fused[2].chunk_id == "keyword-only"


def test_rrf_dense_only_results_keep_dense_order() -> None:
    dense = [_dense("a"), _dense("b"), _dense("c")]

    fused = reciprocal_rank_fusion(dense, [], top_k=3)

    assert [item.chunk_id for item in fused] == ["a", "b", "c"]
