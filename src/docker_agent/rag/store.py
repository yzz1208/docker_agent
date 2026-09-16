from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from docker_agent.db import create_db_engine
from docker_agent.rag.models import Base, DocumentChunk


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
