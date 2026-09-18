from __future__ import annotations

import re
from dataclasses import dataclass

from docker_agent.agent.evidence import RuntimeEvidenceContext, RuntimeEvidenceSource
from docker_agent.rag.answer import CitationValidationError, select_cited_sources
from docker_agent.rag.context import CitationSource, RagContext
from docker_agent.rag.llm import ChatModel

_RUNTIME_CITATION_RE = re.compile(r"\[R(\d+)\]")

AGENT_SYSTEM_PROMPT = """You are a Docker technical support agent.
Use only the evidence supplied in the user prompt.

Evidence types:
- Docker documentation citations use numeric labels such as [1], [2].
- Current local Docker runtime evidence uses labels such as [R1], [R2].

Rules:
- Cite current runtime observations with [R1]-style citations.
- Cite Docker behavior, configuration guidance, and commands with documentation citations.
- Clearly distinguish observed runtime facts from interpretation or general guidance.
- Never invent container state, logs, resource usage, commands, flags, configuration, or citations.
- A successful tool result reports an observation, not automatically the root cause.
- If the evidence is insufficient to identify a root cause, say what remains uncertain.
- If a runtime tool failed, report the failure instead of pretending that evidence was obtained.
- Answer in the same language as the user's question unless the user asks otherwise.
- Do not add a Sources section; the application renders evidence sources separately."""


@dataclass(frozen=True, slots=True)
class AgentAnswer:
    answer: str
    doc_sources: tuple[CitationSource, ...]
    cited_doc_sources: tuple[CitationSource, ...]
    doc_citation_indices: tuple[int, ...]
    runtime_sources: tuple[RuntimeEvidenceSource, ...]
    cited_runtime_sources: tuple[RuntimeEvidenceSource, ...]
    runtime_citation_indices: tuple[int, ...]
    docs_context_truncated: bool
    runtime_context_truncated: bool


def extract_runtime_citation_indices(answer: str) -> tuple[int, ...]:
    """Return unique [R<n>] citation indices in first-appearance order."""

    indices: list[int] = []
    seen: set[int] = set()
    for raw_index in _RUNTIME_CITATION_RE.findall(answer):
        index = int(raw_index)
        if index in seen:
            continue
        seen.add(index)
        indices.append(index)
    return tuple(indices)


def select_runtime_sources(
    answer: str,
    sources: tuple[RuntimeEvidenceSource, ...],
) -> tuple[tuple[int, ...], tuple[RuntimeEvidenceSource, ...]]:
    """Validate runtime citation labels and return cited runtime sources."""

    indices = extract_runtime_citation_indices(answer)
    source_by_index = {source.index: source for source in sources}
    invalid = [index for index in indices if index not in source_by_index]
    if invalid:
        labels = ", ".join(f"[R{index}]" for index in invalid)
        raise CitationValidationError(
            f"Model cited runtime labels that were not provided: {labels}"
        )

    cited = tuple(source_by_index[index] for index in sorted(indices))
    return indices, cited


def build_agent_user_prompt(
    question: str,
    docs_context: RagContext,
    runtime_context: RuntimeEvidenceContext,
) -> str:
    """Build one prompt containing documentation and local runtime evidence."""

    question = question.strip()
    if not question:
        raise ValueError("question must not be empty")
    if not docs_context.text.strip() and not runtime_context.text.strip():
        raise ValueError("at least one evidence context must be non-empty")

    docs_text = docs_context.text or "<no Docker documentation evidence>"
    runtime_text = runtime_context.text or "<no local runtime evidence>"
    doc_labels = (
        ", ".join(f"[{source.index}]" for source in docs_context.sources)
        if docs_context.sources
        else "<none>"
    )
    runtime_labels = (
        ", ".join(f"[R{source.index}]" for source in runtime_context.sources)
        if runtime_context.sources
        else "<none>"
    )

    return (
        "User question:\n"
        f"{question}\n\n"
        "Docker documentation evidence:\n"
        f"{docs_text}\n\n"
        "Local Docker runtime evidence:\n"
        f"{runtime_text}\n\n"
        "Available citation labels:\n"
        f"- Docker Docs: {doc_labels}\n"
        f"- Runtime: {runtime_labels}\n\n"
        "Answer requirements:\n"
        "- Use only the evidence above.\n"
        "- Cite runtime observations with [R1]-style labels.\n"
        "- Cite Docker documentation claims with [1]-style labels only when a Docker Docs "
        "label is available above.\n"
        "- If Docker Docs labels are <none>, do not use numeric citations such as [1].\n"
        "- If Runtime labels are <none>, do not use runtime citations such as [R1].\n"
        "- Do not cite a source that does not support the nearby claim.\n"
        "- Separate observed facts from possible explanations.\n"
        "- If the root cause cannot be proven from the evidence, say so explicitly."
    )



def _repair_invalid_citations(
    *,
    question: str,
    invalid_answer: str,
    validation_error: str,
    docs_context: RagContext,
    runtime_context: RuntimeEvidenceContext,
    model: ChatModel,
) -> str:
    """Ask the model once to repair an otherwise useful answer's citation labels."""

    base_prompt = build_agent_user_prompt(
        question,
        docs_context,
        runtime_context,
    )
    repair_prompt = (
        f"{base_prompt}\n\n"
        "The previous answer failed citation validation:\n"
        f"{validation_error}\n\n"
        "Previous answer:\n"
        f"{invalid_answer}\n\n"
        "Rewrite the answer with the same supported substance, but use only the "
        "available citation labels listed above. Do not introduce new facts."
    )
    return model.complete(
        system_prompt=AGENT_SYSTEM_PROMPT,
        user_prompt=repair_prompt,
    )


def generate_agent_answer(
    question: str,
    docs_context: RagContext,
    runtime_context: RuntimeEvidenceContext,
    model: ChatModel,
) -> AgentAnswer:
    """Generate and validate a combined docs + runtime grounded answer."""

    prompt = build_agent_user_prompt(question, docs_context, runtime_context)
    answer = model.complete(system_prompt=AGENT_SYSTEM_PROMPT, user_prompt=prompt)

    try:
        doc_indices, cited_docs = select_cited_sources(
            answer,
            docs_context.sources,
        )
        runtime_indices, cited_runtime = select_runtime_sources(
            answer,
            runtime_context.sources,
        )
    except CitationValidationError as exc:
        answer = _repair_invalid_citations(
            question=question,
            invalid_answer=answer,
            validation_error=str(exc),
            docs_context=docs_context,
            runtime_context=runtime_context,
            model=model,
        )
        doc_indices, cited_docs = select_cited_sources(
            answer,
            docs_context.sources,
        )
        runtime_indices, cited_runtime = select_runtime_sources(
            answer,
            runtime_context.sources,
        )

    return AgentAnswer(
        answer=answer,
        doc_sources=docs_context.sources,
        cited_doc_sources=cited_docs,
        doc_citation_indices=doc_indices,
        runtime_sources=runtime_context.sources,
        cited_runtime_sources=cited_runtime,
        runtime_citation_indices=runtime_indices,
        docs_context_truncated=docs_context.truncated,
        runtime_context_truncated=runtime_context.truncated,
    )
