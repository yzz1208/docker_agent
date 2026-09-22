from collections.abc import Sequence


def build_embedding_text(
    *,
    title: str,
    section_path: Sequence[str],
    content: str,
) -> str:
    """Build the text sent to the embedding model for one document chunk.

    Titles and section hierarchy are included because technical questions often
    match headings more strongly than nearby prose alone.
    """

    section = " > ".join(part.strip() for part in section_path if part.strip())
    parts = [f"Document: {title.strip()}"]
    if section:
        parts.append(f"Section: {section}")
    parts.append(content.strip())
    return "\n".join(parts).strip()
