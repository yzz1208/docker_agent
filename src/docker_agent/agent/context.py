from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SpecialistUserContext:
    """User-authored context extracted from an internal orchestration wrapper."""

    original_query: str
    current_message: str
    explicit_clarification: str | None = None
    structured: bool = False

    def render(self) -> str:
        parts: list[str] = []
        if (
            self.original_query.strip()
            and self.original_query.strip() != self.current_message.strip()
        ):
            parts.extend(
                [
                    "Original user issue:",
                    self.original_query.strip(),
                    "",
                ]
            )
        parts.extend(
            [
                "Current user request:",
                self.current_message.strip(),
            ]
        )
        if self.explicit_clarification:
            parts.extend(
                [
                    "",
                    "Explicit user clarification:",
                    self.explicit_clarification.strip(),
                ]
            )
        return "\n".join(parts).strip()


def extract_specialist_user_context(value: str) -> SpecialistUserContext:
    """Strip orchestration metadata while preserving only user-authored text.

    Cross-Agent envelopes can contain previous specialist output. That output is
    intentionally not returned here, so a target specialist cannot accidentally
    treat an earlier assistant answer or clarification as the new user request.
    """

    normalized = value.strip()
    if not normalized:
        raise ValueError("value must not be empty")

    original = _section(
        normalized,
        (
            "Original user query:\n",
            "Original topic:\n",
        ),
        (
            "\n\nCurrent user message:\n",
            "\n\nCurrent user request:\n",
            "\n\nCurrent follow-up:\n",
        ),
    )
    current = _section(
        normalized,
        (
            "Current user message:\n",
            "Current user request:\n",
            "Current follow-up:\n",
            "当前用户消息：\n",
        ),
        (
            "\n\nExplicit user clarification:\n",
            "\n\nHandoff metadata:\n",
            "\n\nYour previous public result:\n",
            "\n\nPrior specialist public result:\n",
            "\n\nBoundary rules:\n",
        ),
    )
    clarification = _section(
        normalized,
        ("Explicit user clarification:\n",),
        (
            "\n\nHandoff metadata:\n",
            "\n\nPrior specialist public result:\n",
            "\n\nBoundary rules:\n",
        ),
    )

    if current is None:
        return SpecialistUserContext(
            original_query=normalized,
            current_message=normalized,
            explicit_clarification=None,
            structured=False,
        )

    if clarification in {None, "<none>"}:
        clarification = None
    return SpecialistUserContext(
        original_query=(original or current).strip(),
        current_message=current.strip(),
        explicit_clarification=clarification,
        structured=True,
    )


def specialist_user_text(value: str) -> str:
    context = extract_specialist_user_context(value)
    if not context.structured:
        return context.current_message
    return context.render()


def _section(
    text: str,
    markers: tuple[str, ...],
    terminators: tuple[str, ...],
) -> str | None:
    start = -1
    marker = ""
    for candidate in markers:
        found = text.find(candidate)
        if found >= 0 and (start < 0 or found < start):
            start = found
            marker = candidate
    if start < 0:
        return None

    body_start = start + len(marker)
    end = len(text)
    for terminator in terminators:
        found = text.find(terminator, body_start)
        if found >= 0:
            end = min(end, found)
    value = text[body_start:end].strip()
    return value or None


__all__ = [
    "SpecialistUserContext",
    "extract_specialist_user_context",
    "specialist_user_text",
]
