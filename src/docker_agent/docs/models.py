from dataclasses import asdict, dataclass


@dataclass(slots=True)
class Document:
    """A cleaned Docker Docs source document."""

    document_id: str
    source: str
    file_path: str
    title: str
    source_url: str
    language: str
    content: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class Chunk:
    """A retrieval unit derived from one Document."""

    chunk_id: str
    document_id: str
    title: str
    section_path: list[str]
    content: str
    source_url: str
    file_path: str
    word_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
