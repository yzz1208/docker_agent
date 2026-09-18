from __future__ import annotations

import re
from dataclasses import dataclass

from docker_agent.rag.context import CitationSource, RagContext
from docker_agent.rag.llm import ChatModel

_CITATION_RE = re.compile(r"\[(\d+)\]")

SYSTEM_PROMPT = """You are a Docker technical support assistant.
Use only the Docker documentation excerpts provided in the user prompt as factual support.
Do not invent Docker behavior, commands, flags, configuration keys, or citations.
If the excerpts are insufficient to answer an important part of the question, say that the
provided documentation is insufficient for that part.
Answer in the same language as the user's question unless the user asks otherwise.
Cite supported technical claims with the provided citation labels such as [1] or [2].
Only use citation numbers that appear in the provided context.
Prefer concrete troubleshooting steps and commands when they are supported by the context."""


class CitationValidationError(ValueError):
    """Raised when an answer cites a source label that was not provided."""


@dataclass(frozen=True, slots=True)
class GroundedAnswer:
    answer: str
    sources: tuple[CitationSource, ...]
    cited_sources: tuple[CitationSource, ...]
    citation_indices: tuple[int, ...]
    context_truncated: bool


def extract_citation_indices(answer: str) -> tuple[int, ...]:
    """Return unique citation numbers in first-appearance order."""

    indices: list[int] = []
    seen: set[int] = set()
    for raw_index in _CITATION_RE.findall(answer):
        index = int(raw_index)
        if index in seen:
            continue
        seen.add(index)
        indices.append(index)
    return tuple(indices)


def select_cited_sources(
    answer: str,
    sources: tuple[CitationSource, ...],
) -> tuple[tuple[int, ...], tuple[CitationSource, ...]]:
    """Validate citation labels and return cited sources in numeric label order."""

    citation_indices = extract_citation_indices(answer)
    source_by_index = {source.index: source for source in sources}
    invalid = [index for index in citation_indices if index not in source_by_index]
    if invalid:
        labels = ", ".join(f"[{index}]" for index in invalid)
        raise CitationValidationError(
            f"Model cited source labels that were not provided: {labels}"
        )

    cited_sources = tuple(
        source_by_index[index] for index in sorted(citation_indices)
    )
    return citation_indices, cited_sources


def build_user_prompt(question: str, context: RagContext) -> str:
    question = question.strip()
    if not question:
        raise ValueError("question must not be empty")
    if not context.sources or not context.text.strip():
        raise ValueError("context must contain at least one source")

    return (
        "User question:\n"
        f"{question}\n\n"
        "Retrieved Docker documentation:\n"
        f"{context.text}\n\n"
        "Answer requirements:\n"
        "- Base the answer only on the retrieved documentation above.\n"
        "- Put citations immediately after the claims they support, for example [1].\n"
        "- Do not cite a source that does not support the claim.\n"
        "- If the documentation is insufficient, explicitly say what cannot be concluded.\n"
        "- Do not add a separate Sources section; the application will render sources."
    )


def generate_grounded_answer(
    question: str,
    context: RagContext,
    model: ChatModel,
) -> GroundedAnswer:
    user_prompt = build_user_prompt(question, context)
    answer = model.complete(system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt)
    citation_indices, cited_sources = select_cited_sources(answer, context.sources)
    return GroundedAnswer(
        answer=answer,
        sources=context.sources,
        cited_sources=cited_sources,
        citation_indices=citation_indices,
        context_truncated=context.truncated,
    )
