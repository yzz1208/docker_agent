from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.engine import Engine

from docker_agent.agent.protocol import PersistableAgentTurnProtocol
from docker_agent.graph.service import LangGraphAgentTurnResult
from docker_agent.persistence.store import (
    ExecutionRecord,
    MessageRecord,
    append_message,
    reserve_message_timestamps,
    save_execution,
)


@dataclass(frozen=True, slots=True)
class PersistedAgentTurn:
    """Durable records created for one completed Agent chat turn."""

    user_message: MessageRecord
    assistant_message: MessageRecord
    execution: ExecutionRecord


def persist_agent_turn(
    engine: Engine,
    *,
    conversation_id: str,
    user_message: str,
    result: PersistableAgentTurnProtocol,
) -> PersistedAgentTurn:
    """Persist one generic Agent turn plus safe orchestration metadata."""

    assistant_content = _assistant_content(result)
    user_created_at, assistant_created_at = reserve_message_timestamps(
        engine,
        conversation_id=conversation_id,
        count=2,
    )

    user_record = append_message(
        engine,
        conversation_id=conversation_id,
        role="user",
        content=user_message,
        created_at=user_created_at,
    )
    assistant_record = append_message(
        engine,
        conversation_id=conversation_id,
        role="assistant",
        content=assistant_content,
        route=result.decision.route,
        use_docs=result.decision.use_docs,
        clarification=(
            result.decision.clarification
            if result.needs_clarification
            else None
        ),
        created_at=assistant_created_at,
    )
    execution_record = save_execution(
        engine,
        message_id=assistant_record.id,
        planned_workers=result.supervisor_plan.workers,
        completed_workers=tuple(
            record.role
            for record in result.worker_trace
        ),
        worker_trace=_safe_execution_trace(result),
    )

    return PersistedAgentTurn(
        user_message=user_record,
        assistant_message=assistant_record,
        execution=execution_record,
    )


def _safe_execution_trace(
    result: PersistableAgentTurnProtocol,
) -> tuple[dict[str, object], ...]:
    trace: list[dict[str, object]] = [
        {
            "index": record.index,
            "role": record.role,
            "tool_results_added": record.tool_results_added,
            "evidence_added": record.evidence_added,
            "runtime_steps_added": record.runtime_steps_added,
            "answer_created": record.answer_created,
        }
        for record in result.worker_trace
    ]

    if result.answer is None:
        return tuple(trace)

    trace.extend(
        {
            "kind": "doc_source",
            "index": source.index,
            "title": source.title,
            "section": source.section,
            "source_url": source.source_url,
        }
        for source in result.answer.cited_doc_sources
    )
    trace.extend(
        {
            "kind": "runtime_source",
            "index": source.index,
            "tool": source.tool,
            "command": list(source.command),
            "ok": source.ok,
        }
        for source in result.answer.cited_runtime_sources
    )
    trace.append(
        {
            "kind": "answer_context",
            "docs_context_truncated": result.answer.docs_context_truncated,
            "runtime_context_truncated": result.answer.runtime_context_truncated,
        }
    )
    return tuple(trace)


def persist_langgraph_turn(
    engine: Engine,
    *,
    conversation_id: str,
    user_message: str,
    result: LangGraphAgentTurnResult,
) -> PersistedAgentTurn:
    """Compatibility wrapper for the Docker LangGraph Agent."""

    return persist_agent_turn(
        engine,
        conversation_id=conversation_id,
        user_message=user_message,
        result=result,
    )


def _assistant_content(
    result: PersistableAgentTurnProtocol,
) -> str:
    if result.answer is not None:
        return result.answer.answer

    clarification = result.decision.clarification
    if result.needs_clarification and clarification is not None:
        normalized = clarification.strip()
        if normalized:
            return normalized

    raise ValueError(
        "Agent turn has neither answer nor clarification content"
    )
