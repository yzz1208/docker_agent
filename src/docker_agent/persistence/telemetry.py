from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import uuid4

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from docker_agent.persistence.models import AgentRun, Conversation, utc_now

AgentRunStatus = Literal["running", "succeeded", "failed"]

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+\-/=]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
)


@dataclass(frozen=True, slots=True)
class AgentRunRecord:
    id: str
    conversation_id: str
    agent_type: str
    status: AgentRunStatus
    route: str | None
    use_docs: bool | None
    planned_workers: tuple[str, ...]
    completed_workers: tuple[str, ...]
    duration_ms: int | None
    error_type: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None


class AgentRunNotFound(KeyError):
    """Raised when one telemetry run does not exist."""


class AgentRunStateError(ValueError):
    """Raised when an invalid run lifecycle transition is requested."""


def create_agent_run(
    engine: Engine,
    *,
    conversation_id: str,
    agent_type: str,
    run_id: str | None = None,
) -> AgentRunRecord:
    normalized_conversation_id = conversation_id.strip()
    normalized_agent_type = agent_type.strip()

    if not normalized_conversation_id:
        raise ValueError("conversation_id must not be empty")
    if not normalized_agent_type:
        raise ValueError("agent_type must not be empty")

    with Session(engine) as session:
        if session.get(Conversation, normalized_conversation_id) is None:
            raise ValueError(
                f"conversation {normalized_conversation_id!r} does not exist"
            )

        row = AgentRun(
            id=run_id or uuid4().hex,
            conversation_id=normalized_conversation_id,
            agent_type=normalized_agent_type,
            status="running",
            planned_workers=[],
            completed_workers=[],
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _agent_run_record(row)


def get_agent_run(
    engine: Engine,
    run_id: str,
) -> AgentRunRecord:
    normalized = run_id.strip()
    if not normalized:
        raise ValueError("run_id must not be empty")

    with Session(engine) as session:
        row = session.get(AgentRun, normalized)
        if row is None:
            raise AgentRunNotFound(normalized)
        return _agent_run_record(row)


def finalize_agent_run_success(
    engine: Engine,
    run_id: str,
    *,
    route: str,
    use_docs: bool,
    planned_workers: tuple[str, ...] | list[str],
    completed_workers: tuple[str, ...] | list[str],
    duration_ms: int,
) -> AgentRunRecord:
    return _finalize_agent_run(
        engine,
        run_id,
        status="succeeded",
        route=route,
        use_docs=use_docs,
        planned_workers=planned_workers,
        completed_workers=completed_workers,
        duration_ms=duration_ms,
        error_type=None,
        error_message=None,
    )


def finalize_agent_run_failure(
    engine: Engine,
    run_id: str,
    *,
    duration_ms: int,
    error: BaseException,
    route: str | None = None,
    use_docs: bool | None = None,
    planned_workers: tuple[str, ...] | list[str] = (),
    completed_workers: tuple[str, ...] | list[str] = (),
) -> AgentRunRecord:
    return _finalize_agent_run(
        engine,
        run_id,
        status="failed",
        route=route,
        use_docs=use_docs,
        planned_workers=planned_workers,
        completed_workers=completed_workers,
        duration_ms=duration_ms,
        error_type=type(error).__name__,
        error_message=safe_error_message(error),
    )


def safe_error_message(
    error: BaseException,
    *,
    max_chars: int = 500,
) -> str | None:
    message = " ".join(str(error).split())
    if not message:
        return None

    for pattern in _SECRET_PATTERNS:
        message = pattern.sub(_redact_match, message)

    if len(message) > max_chars:
        return message[: max_chars - 1].rstrip() + "…"
    return message


def _redact_match(match: re.Match[str]) -> str:
    text = match.group(0)
    if text.lower().startswith("bearer "):
        return "Bearer [REDACTED]"
    if text.lower().startswith("sk-"):
        return "[REDACTED]"
    key = re.split(r"[:=]", text, maxsplit=1)[0].strip()
    return f"{key}=[REDACTED]"


def _finalize_agent_run(
    engine: Engine,
    run_id: str,
    *,
    status: Literal["succeeded", "failed"],
    route: str | None,
    use_docs: bool | None,
    planned_workers: tuple[str, ...] | list[str],
    completed_workers: tuple[str, ...] | list[str],
    duration_ms: int,
    error_type: str | None,
    error_message: str | None,
) -> AgentRunRecord:
    normalized = run_id.strip()
    if not normalized:
        raise ValueError("run_id must not be empty")
    if duration_ms < 0:
        raise ValueError("duration_ms must not be negative")

    with Session(engine) as session:
        row = session.get(AgentRun, normalized)
        if row is None:
            raise AgentRunNotFound(normalized)
        if row.status != "running":
            raise AgentRunStateError(
                f"agent run {normalized!r} is already finalized"
            )

        row.status = status
        row.route = route
        row.use_docs = use_docs
        row.planned_workers = list(planned_workers)
        row.completed_workers = list(completed_workers)
        row.duration_ms = duration_ms
        row.error_type = error_type
        row.error_message = error_message
        row.completed_at = utc_now()

        session.commit()
        session.refresh(row)
        return _agent_run_record(row)


def _agent_run_record(row: AgentRun) -> AgentRunRecord:
    status = row.status
    if status not in {"running", "succeeded", "failed"}:
        raise ValueError(f"invalid stored agent run status: {status}")

    return AgentRunRecord(
        id=row.id,
        conversation_id=row.conversation_id,
        agent_type=row.agent_type,
        status=status,
        route=row.route,
        use_docs=row.use_docs,
        planned_workers=tuple(str(item) for item in row.planned_workers),
        completed_workers=tuple(str(item) for item in row.completed_workers),
        duration_ms=row.duration_ms,
        error_type=row.error_type,
        error_message=row.error_message,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )
