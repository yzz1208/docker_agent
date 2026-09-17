from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from docker_agent.db import create_db_engine
from docker_agent.rag.models import Base, DocumentChunk

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_]{1,63}")
_KEYWORD_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "can",
        "do",
        "docker",
        "for",
        "from",
        "how",
        "i",
        "in",
        "inside",
        "into",
        "is",
        "it",
        "my",
        "of",
        "on",
        "or",
        "should",
        "that",
        "the",
        "this",
        "to",
        "use",
        "using",
        "want",
        "what",
        "when",
        "why",
        "with",
    }
)


@dataclass(slots=True)
class SearchResult:
    chunk_id: str
    document_id: str
    title: str
    section_path: list[str]
    content: str
    source_url: str
    file_path: str
    distance: float

    @property
    def score(self) -> float:
        """Convert cosine distance to cosine similarity."""

        return 1.0 - self.distance


@dataclass(slots=True)
class KeywordSearchResult:
    chunk_id: str
    document_id: str
    title: str
    section_path: list[str]
    content: str
    source_url: str
    file_path: str
    rank_score: float


@dataclass(slots=True)
class HybridSearchResult:
    chunk_id: str
    document_id: str
    title: str
    section_path: list[str]
    content: str
    source_url: str
    file_path: str
    rrf_score: float
    dense_rank: int | None
    keyword_rank: int | None
    dense_distance: float | None
    keyword_score: float | None
    rerank_score: float | None = None


def init_vector_store(engine: Engine | None = None) -> Engine:
    """Ensure pgvector and the document chunk table exist."""

    engine = engine or create_db_engine(register_pgvector_types=False)
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    return engine


def clear_chunks(engine: Engine) -> None:
    """Delete every indexed document chunk."""

    with Session(engine) as session:
        session.execute(delete(DocumentChunk))
        session.commit()


def upsert_chunk_batch(
    engine: Engine,
    rows: list[dict[str, object]],
    embeddings: list[list[float]],
) -> int:
    """Insert or update one aligned batch of chunks and embeddings."""

    if len(rows) != len(embeddings):
        raise ValueError("Rows and embeddings must have the same length")
    if not rows:
        return 0

    payload: list[dict[str, object]] = []
    for row, embedding in zip(rows, embeddings, strict=True):
        section_path = row.get("section_path")
        if not isinstance(section_path, list):
            raise TypeError("section_path must be a list")

        payload.append(
            {
                "chunk_id": str(row["chunk_id"]),
                "document_id": str(row["document_id"]),
                "title": str(row["title"]),
                "section_path": [str(part) for part in section_path],
                "content": str(row["content"]),
                "source_url": str(row["source_url"]),
                "file_path": str(row["file_path"]),
                "embedding": embedding,
            }
        )

    statement = insert(DocumentChunk).values(payload)
    statement = statement.on_conflict_do_update(
        index_elements=[DocumentChunk.chunk_id],
        set_={
            "document_id": statement.excluded.document_id,
            "title": statement.excluded.title,
            "section_path": statement.excluded.section_path,
            "content": statement.excluded.content,
            "source_url": statement.excluded.source_url,
            "file_path": statement.excluded.file_path,
            "embedding": statement.excluded.embedding,
        },
    )

    with Session(engine) as session:
        session.execute(statement)
        session.commit()
    return len(payload)


def search_similar_chunks(
    engine: Engine,
    query_embedding: list[float],
    *,
    top_k: int = 5,
) -> list[SearchResult]:
    """Return nearest chunks using exact cosine distance in pgvector."""

    if top_k <= 0:
        raise ValueError("top_k must be positive")

    distance = DocumentChunk.embedding.cosine_distance(query_embedding)
    statement = (
        select(DocumentChunk, distance.label("distance"))
        .order_by(distance)
        .limit(top_k)
    )

    results: list[SearchResult] = []
    with Session(engine) as session:
        for chunk, raw_distance in session.execute(statement):
            results.append(
                SearchResult(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    title=chunk.title,
                    section_path=list(chunk.section_path),
                    content=chunk.content,
                    source_url=chunk.source_url,
                    file_path=chunk.file_path,
                    distance=float(raw_distance),
                )
            )
    return results


def extract_keyword_terms(query: str, *, max_terms: int = 12) -> list[str]:
    """Extract ASCII technical terms for PostgreSQL full-text retrieval.

    Dense retrieval handles cross-language semantics. Keyword retrieval focuses on
    exact technical anchors such as DOCKER_HOST, iptables, env_file, 137, tmpfs,
    and English product terms that survive inside an otherwise Chinese query.
    """

    if max_terms <= 0:
        raise ValueError("max_terms must be positive")

    terms: list[str] = []
    seen: set[str] = set()
    for raw in _TOKEN_RE.findall(query):
        term = raw.casefold()
        if term in _KEYWORD_STOPWORDS or term in seen:
            continue
        if len(term) < 2 and not term.isdigit():
            continue
        seen.add(term)
        terms.append(term)
        if len(terms) >= max_terms:
            break
    return terms


def search_keyword_chunks(
    engine: Engine,
    query: str,
    *,
    top_k: int = 20,
) -> list[KeywordSearchResult]:
    """Search exact technical terms with PostgreSQL full-text search.

    Terms are OR-combined intentionally. Chinese semantic meaning is handled by
    BGE-M3; this retriever is meant to add exact lexical evidence rather than
    replace dense retrieval.
    """

    if top_k <= 0:
        raise ValueError("top_k must be positive")

    terms = extract_keyword_terms(query)
    if not terms:
        return []

    ts_query = " | ".join(terms)
    statement = text(
        """
        WITH query_input AS (
            SELECT to_tsquery('simple', :ts_query) AS query
        ), ranked AS (
            SELECT
                dc.chunk_id,
                dc.document_id,
                dc.title,
                dc.section_path,
                dc.content,
                dc.source_url,
                dc.file_path,
                ts_rank_cd(
                    setweight(to_tsvector('simple', coalesce(dc.title, '')), 'A') ||
                    setweight(to_tsvector('simple', coalesce(dc.section_path::text, '')), 'A') ||
                    setweight(to_tsvector('simple', coalesce(dc.content, '')), 'B'),
                    qi.query,
                    32
                ) AS rank_score
            FROM document_chunks AS dc
            CROSS JOIN query_input AS qi
            WHERE (
                setweight(to_tsvector('simple', coalesce(dc.title, '')), 'A') ||
                setweight(to_tsvector('simple', coalesce(dc.section_path::text, '')), 'A') ||
                setweight(to_tsvector('simple', coalesce(dc.content, '')), 'B')
            ) @@ qi.query
        )
        SELECT *
        FROM ranked
        ORDER BY rank_score DESC, chunk_id
        LIMIT :top_k
        """
    )

    results: list[KeywordSearchResult] = []
    with engine.connect() as connection:
        rows = connection.execute(
            statement,
            {"ts_query": ts_query, "top_k": top_k},
        )
        for row in rows.mappings():
            section_path = row["section_path"]
            if not isinstance(section_path, list):
                raise TypeError("PostgreSQL returned a non-list section_path")
            results.append(
                KeywordSearchResult(
                    chunk_id=str(row["chunk_id"]),
                    document_id=str(row["document_id"]),
                    title=str(row["title"]),
                    section_path=[str(part) for part in section_path],
                    content=str(row["content"]),
                    source_url=str(row["source_url"]),
                    file_path=str(row["file_path"]),
                    rank_score=float(row["rank_score"]),
                )
            )
    return results


def reciprocal_rank_fusion(
    dense_results: list[SearchResult],
    keyword_results: list[KeywordSearchResult],
    *,
    top_k: int = 5,
    rrf_k: int = 60,
    dense_weight: float = 1.0,
    keyword_weight: float = 1.0,
) -> list[HybridSearchResult]:
    """Fuse dense and lexical rankings with weighted Reciprocal Rank Fusion."""

    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if rrf_k < 0:
        raise ValueError("rrf_k must be non-negative")
    if dense_weight < 0 or keyword_weight < 0:
        raise ValueError("RRF weights must be non-negative")
    if dense_weight == 0 and keyword_weight == 0:
        raise ValueError("At least one RRF weight must be positive")

    combined: dict[str, HybridSearchResult] = {}

    for rank, result in enumerate(dense_results, start=1):
        combined[result.chunk_id] = HybridSearchResult(
            chunk_id=result.chunk_id,
            document_id=result.document_id,
            title=result.title,
            section_path=result.section_path,
            content=result.content,
            source_url=result.source_url,
            file_path=result.file_path,
            rrf_score=dense_weight / (rrf_k + rank),
            dense_rank=rank,
            keyword_rank=None,
            dense_distance=result.distance,
            keyword_score=None,
        )

    for rank, result in enumerate(keyword_results, start=1):
        contribution = keyword_weight / (rrf_k + rank)
        existing = combined.get(result.chunk_id)
        if existing is None:
            combined[result.chunk_id] = HybridSearchResult(
                chunk_id=result.chunk_id,
                document_id=result.document_id,
                title=result.title,
                section_path=result.section_path,
                content=result.content,
                source_url=result.source_url,
                file_path=result.file_path,
                rrf_score=contribution,
                dense_rank=None,
                keyword_rank=rank,
                dense_distance=None,
                keyword_score=result.rank_score,
            )
        else:
            existing.rrf_score += contribution
            existing.keyword_rank = rank
            existing.keyword_score = result.rank_score

    return sorted(
        combined.values(),
        key=lambda item: (
            -item.rrf_score,
            item.dense_rank if item.dense_rank is not None else 10**9,
            item.keyword_rank if item.keyword_rank is not None else 10**9,
            item.chunk_id,
        ),
    )[:top_k]


def search_hybrid_chunks(
    engine: Engine,
    query: str,
    query_embedding: list[float],
    *,
    top_k: int = 5,
    candidate_k: int = 20,
    rrf_k: int = 60,
    dense_weight: float = 1.0,
    keyword_weight: float = 1.0,
) -> list[HybridSearchResult]:
    """Combine dense pgvector retrieval and PostgreSQL FTS with weighted RRF."""

    if candidate_k < top_k:
        raise ValueError("candidate_k must be greater than or equal to top_k")

    dense_results = search_similar_chunks(engine, query_embedding, top_k=candidate_k)
    keyword_results = search_keyword_chunks(engine, query, top_k=candidate_k)
    return reciprocal_rank_fusion(
        dense_results,
        keyword_results,
        top_k=top_k,
        rrf_k=rrf_k,
        dense_weight=dense_weight,
        keyword_weight=keyword_weight,
    )
