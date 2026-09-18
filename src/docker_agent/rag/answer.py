from __future__ import annotations

from dataclasses import dataclass

from docker_agent.rag.context import CitationSource, RagContext
from docker_agent.rag.llm import ChatModel

SYSTEM_PROMPT = """You are a Docker technical support assistant.
Use only the Docker documentation excerpts provided in the user prompt as factual support.
Do not invent Docker behavior, commands, flags, configuration keys, or citations.
If the excerpts are insufficient to answer an important part of the question, say that the
provided documentation is insufficient for that part.
Answer in the same language as the user's question unless the user asks otherwise.
Cite supported technical claims with the provided citation labels such as [1] or [2].
Only use citation numbers that appear in the provided context.
Prefer concrete troubleshooting steps and commands when they are supported by the context."""


@dataclass(frozen=True, slots=True)
class GroundedAnswer:
    answer: str
    sources: tuple[CitationSource, ...]
    context_truncated: bool


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
    return GroundedAnswer(
        answer=answer,
        sources=context.sources,
        context_truncated=context.truncated,
    )
