from dataclasses import dataclass

import pytest

from docker_agent.conversation_context import (
    apply_conversation_context,
    build_conversation_context,
)


@dataclass(frozen=True)
class Message:
    role: str
    content: str


def test_context_keeps_newest_messages_in_chronological_order() -> None:
    messages = (
        Message("user", "first"),
        Message("assistant", "second"),
        Message("user", "third"),
        Message("assistant", "fourth"),
    )

    context = build_conversation_context(
        messages,
        max_messages=3,
        max_chars=1000,
    )

    assert context.message_count == 3
    assert context.available_message_count == 4
    assert context.truncated is True
    assert context.text == (
        "[assistant] second\n\n"
        "[user] third\n\n"
        "[assistant] fourth"
    )


def test_context_drops_older_messages_when_character_budget_is_hit() -> None:
    messages = (
        Message("user", "older message"),
        Message("assistant", "newer answer"),
    )
    newest = "[assistant] newer answer"

    context = build_conversation_context(
        messages,
        max_messages=10,
        max_chars=len(newest),
    )

    assert context.text == newest
    assert context.message_count == 1
    assert context.truncated is True


def test_context_truncates_single_newest_message_when_needed() -> None:
    messages = (
        Message("assistant", "abcdefghijklmnopqrstuvwxyz"),
    )

    context = build_conversation_context(
        messages,
        max_messages=5,
        max_chars=12,
    )

    assert len(context.text) <= 12
    assert context.text.endswith("…")
    assert context.message_count == 1
    assert context.truncated is True


@pytest.mark.parametrize(
    ("max_messages", "max_chars"),
    [
        (0, 100),
        (10, 0),
    ],
)
def test_zero_budget_disables_context(
    max_messages: int,
    max_chars: int,
) -> None:
    context = build_conversation_context(
        (Message("user", "hello"),),
        max_messages=max_messages,
        max_chars=max_chars,
    )

    assert context.empty is True
    assert context.message_count == 0
    assert context.truncated is True


def test_context_rejects_negative_budgets() -> None:
    with pytest.raises(
        ValueError,
        match="max_messages must not be negative",
    ):
        build_conversation_context(
            (),
            max_messages=-1,
            max_chars=100,
        )

    with pytest.raises(
        ValueError,
        match="max_chars must not be negative",
    ):
        build_conversation_context(
            (),
            max_messages=1,
            max_chars=-1,
        )


def test_apply_context_separates_history_from_current_message() -> None:
    prompt = apply_conversation_context(
        "What about the dependency?",
        "[user] api returns 503\n\n[assistant] Check scope.",
    )

    assert "BEGIN PRIOR CONVERSATION" in prompt
    assert "[user] api returns 503" in prompt
    assert "Current user message:\nWhat about the dependency?" in prompt


def test_apply_context_without_history_keeps_question_unchanged() -> None:
    assert apply_conversation_context("  hello  ", None) == "hello"
