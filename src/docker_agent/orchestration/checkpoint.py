from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url

from docker_agent.config import get_settings
from docker_agent.orchestration.decision import OrchestrationDecision
from docker_agent.orchestration.delegation import (
    AgentHandoff,
    DelegationContext,
)
from docker_agent.orchestration.envelope import SpecialistResultEnvelope
from docker_agent.orchestration.synthesis import OrchestratedSynthesisResult

CHECKPOINT_NAMESPACE = "phase9_orchestration"


def postgres_checkpoint_uri(database_url: str) -> str:
    """Convert the SQLAlchemy PostgreSQL URL into a psycopg URI."""

    normalized = database_url.strip()
    if not normalized:
        raise ValueError("database_url must not be empty")

    url = make_url(normalized)
    if url.get_backend_name() != "postgresql":
        raise ValueError(
            "LangGraph durable checkpoints require PostgreSQL"
        )
    return url.set(drivername="postgresql").render_as_string(
        hide_password=False
    )


def orchestration_checkpoint_serializer() -> JsonPlusSerializer:
    """Return an allowlisted serializer for public orchestration state."""

    return JsonPlusSerializer(
        pickle_fallback=False,
        allowed_msgpack_modules=[
            AgentHandoff,
            DelegationContext,
            OrchestrationDecision,
            OrchestratedSynthesisResult,
            SpecialistResultEnvelope,
        ],
    )


@contextmanager
def open_postgres_orchestration_checkpointer(
    *,
    database_url: str | None = None,
    setup: bool = False,
) -> Iterator[PostgresSaver]:
    """Open the production Postgres saver for Phase 9 orchestration.

    setup=True is intended for an explicit deployment/setup command, not for
    every application startup.
    """

    resolved_url = database_url or get_settings().database_url
    uri = postgres_checkpoint_uri(resolved_url)
    connection = psycopg.connect(
        uri,
        autocommit=True,
        row_factory=dict_row,
    )
    try:
        saver = PostgresSaver(
            connection,
            serde=orchestration_checkpoint_serializer(),
        )
        if setup:
            saver.setup()
        yield saver
    finally:
        connection.close()


def orchestration_thread_config(
    thread_id: str,
) -> dict[str, dict[str, str]]:
    normalized = thread_id.strip()
    if not normalized:
        raise ValueError("thread_id must not be empty")
    return {
        "configurable": {
            "thread_id": normalized,
            "checkpoint_ns": CHECKPOINT_NAMESPACE,
        }
    }


__all__ = [
    "CHECKPOINT_NAMESPACE",
    "open_postgres_orchestration_checkpointer",
    "orchestration_checkpoint_serializer",
    "orchestration_thread_config",
    "postgres_checkpoint_uri",
]
