from __future__ import annotations

from dataclasses import dataclass

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from pgvector.psycopg import register_vector
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

from docker_agent.config import get_settings


@dataclass(frozen=True, slots=True)
class DatabaseReadiness:
    current_revisions: tuple[str, ...]
    head_revisions: tuple[str, ...]
    schema_current: bool


class DatabaseSchemaNotReady(RuntimeError):
    """Raised when the database is reachable but migrations are not current."""


def create_db_engine(*, register_pgvector_types: bool = True) -> Engine:
    """Create a configured SQLAlchemy engine.

    PostgreSQL uses bounded QueuePool settings. SQLite keeps its native pool
    behavior so isolated unit tests remain lightweight.
    """

    settings = get_settings()
    engine_options: dict[str, object] = {
        "pool_pre_ping": True,
    }

    if not settings.database_url.startswith("sqlite"):
        engine_options.update(
            {
                "pool_size": settings.database_pool_size,
                "max_overflow": settings.database_max_overflow,
                "pool_timeout": settings.database_pool_timeout_seconds,
                "pool_recycle": settings.database_pool_recycle_seconds,
            }
        )

    engine = create_engine(
        settings.database_url,
        **engine_options,
    )

    if (
        register_pgvector_types
        and settings.database_url.startswith("postgresql")
    ):

        @event.listens_for(engine, "connect")
        def _register_vector_types(
            dbapi_connection: object,
            _connection_record: object,
        ) -> None:
            register_vector(dbapi_connection)

    return engine


def check_database(engine: Engine | None = None) -> bool:
    """Return True when the configured database accepts a simple query."""

    owns_engine = engine is None
    resolved_engine = engine or create_db_engine(
        register_pgvector_types=False
    )

    try:
        with resolved_engine.connect() as connection:
            return connection.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        if owns_engine:
            resolved_engine.dispose()


def get_database_readiness(engine: Engine) -> DatabaseReadiness:
    """Return database migration readiness for the configured Alembic graph."""

    settings = get_settings()
    config = Config(settings.database_migration_config)
    script = ScriptDirectory.from_config(config)
    head_revisions = tuple(sorted(script.get_heads()))

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        migration_context = MigrationContext.configure(connection)
        current_revisions = tuple(
            sorted(migration_context.get_current_heads())
        )

    return DatabaseReadiness(
        current_revisions=current_revisions,
        head_revisions=head_revisions,
        schema_current=current_revisions == head_revisions,
    )


def require_database_ready(engine: Engine) -> DatabaseReadiness:
    """Require a reachable database migrated to the current Alembic head."""

    readiness = get_database_readiness(engine)
    if not readiness.schema_current:
        current = ", ".join(readiness.current_revisions) or "none"
        expected = ", ".join(readiness.head_revisions) or "none"
        raise DatabaseSchemaNotReady(
            "Database schema is not at Alembic head "
            f"(current={current}, expected={expected}). "
            "Run `uv run alembic upgrade head` before starting the API."
        )
    return readiness
