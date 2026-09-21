from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from docker_agent.config import Settings, get_settings
from docker_agent.db import (
    DatabaseReadiness,
    DatabaseSchemaNotReady,
    create_db_engine,
    get_database_readiness,
    require_database_ready,
)
from docker_agent.main import (
    app,
    get_agent,
    get_chat_coordinator,
    get_persistence_engine,
)


def test_create_db_engine_applies_bounded_pool_settings(
    monkeypatch,
) -> None:
    settings = Settings(
        database_url=(
            "postgresql+psycopg://postgres:postgres@localhost/docker_agent"
        ),
        database_pool_size=7,
        database_max_overflow=11,
        database_pool_timeout_seconds=12.5,
        database_pool_recycle_seconds=900,
    )
    captured: dict[str, object] = {}
    fake_engine = object()

    def fake_create_engine(
        url: str,
        **kwargs: object,
    ) -> object:
        captured["url"] = url
        captured.update(kwargs)
        return fake_engine

    monkeypatch.setattr("docker_agent.db.get_settings", lambda: settings)
    monkeypatch.setattr(
        "docker_agent.db.create_engine",
        fake_create_engine,
    )

    result = create_db_engine(register_pgvector_types=False)

    assert result is fake_engine
    assert captured == {
        "url": settings.database_url,
        "pool_pre_ping": True,
        "pool_size": 7,
        "max_overflow": 11,
        "pool_timeout": 12.5,
        "pool_recycle": 900,
    }


def test_create_db_engine_keeps_sqlite_pool_native(
    monkeypatch,
) -> None:
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
    )
    captured: dict[str, object] = {}
    fake_engine = object()

    def fake_create_engine(
        url: str,
        **kwargs: object,
    ) -> object:
        captured["url"] = url
        captured.update(kwargs)
        return fake_engine

    monkeypatch.setattr("docker_agent.db.get_settings", lambda: settings)
    monkeypatch.setattr(
        "docker_agent.db.create_engine",
        fake_create_engine,
    )

    result = create_db_engine(register_pgvector_types=False)

    assert result is fake_engine
    assert captured == {
        "url": settings.database_url,
        "pool_pre_ping": True,
    }


def test_database_readiness_tracks_alembic_head(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "readiness.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("DATABASE_MIGRATION_CONFIG", "alembic.ini")
    get_settings.cache_clear()

    engine = create_engine(database_url)
    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url",
        database_url.replace("%", "%%"),
    )

    try:
        command.upgrade(config, "head")

        readiness = get_database_readiness(engine)

        assert readiness.schema_current is True
        assert readiness.current_revisions == ("20260921_0001",)
        assert readiness.head_revisions == ("20260921_0001",)
        assert require_database_ready(engine) == readiness

        command.downgrade(config, "base")

        outdated = get_database_readiness(engine)
        assert outdated.schema_current is False
        assert outdated.current_revisions == ()
        assert outdated.head_revisions == ("20260921_0001",)

        with pytest.raises(
            DatabaseSchemaNotReady,
            match="alembic upgrade head",
        ):
            require_database_ready(engine)
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_readiness_endpoint_reports_current_schema(
    monkeypatch,
) -> None:
    readiness = DatabaseReadiness(
        current_revisions=("20260921_0001",),
        head_revisions=("20260921_0001",),
        schema_current=True,
    )
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: object(),
    )
    monkeypatch.setattr(
        "docker_agent.main.get_database_readiness",
        lambda _engine: readiness,
    )
    client = TestClient(app)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "reachable",
        "schema": "current",
        "current_revisions": ["20260921_0001"],
        "head_revisions": ["20260921_0001"],
    }


def test_readiness_endpoint_rejects_outdated_schema(
    monkeypatch,
) -> None:
    readiness = DatabaseReadiness(
        current_revisions=(),
        head_revisions=("20260921_0001",),
        schema_current=False,
    )
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: object(),
    )
    monkeypatch.setattr(
        "docker_agent.main.get_database_readiness",
        lambda _engine: readiness,
    )
    client = TestClient(app)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["schema"] == "outdated"
    assert response.json()["current_revisions"] == []
    assert response.json()["head_revisions"] == ["20260921_0001"]


def test_app_lifespan_disposes_database_engine(
    monkeypatch,
) -> None:
    class FakeEngine:
        disposed = False

        def dispose(self) -> None:
            self.disposed = True

    engine = FakeEngine()
    readiness = DatabaseReadiness(
        current_revisions=("20260921_0001",),
        head_revisions=("20260921_0001",),
        schema_current=True,
    )

    get_persistence_engine.cache_clear()
    get_chat_coordinator.cache_clear()
    get_agent.cache_clear()

    monkeypatch.setattr(
        "docker_agent.main.create_db_engine",
        lambda **_kwargs: engine,
    )
    monkeypatch.setattr(
        "docker_agent.main.require_database_ready",
        lambda _engine: readiness,
    )

    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert engine.disposed is False

    assert engine.disposed is True



def test_app_lifespan_rejects_outdated_database_schema(
    monkeypatch,
) -> None:
    class FakeEngine:
        disposed = False

        def dispose(self) -> None:
            self.disposed = True

    engine = FakeEngine()

    get_persistence_engine.cache_clear()
    get_chat_coordinator.cache_clear()
    get_agent.cache_clear()

    monkeypatch.setattr(
        "docker_agent.main.create_db_engine",
        lambda **_kwargs: engine,
    )

    def reject_schema(_engine: object) -> None:
        raise DatabaseSchemaNotReady("schema is outdated")

    monkeypatch.setattr(
        "docker_agent.main.require_database_ready",
        reject_schema,
    )

    with pytest.raises(
        DatabaseSchemaNotReady,
        match="schema is outdated",
    ):
        with TestClient(app):
            pass

    assert engine.disposed is True


def test_database_health_hides_database_exception_details(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: object(),
    )

    def fail_check(_engine: object) -> bool:
        raise OperationalError(
            "SELECT 1",
            {},
            RuntimeError(
                "postgresql://user:super-secret@database/internal"
            ),
        )

    monkeypatch.setattr(
        "docker_agent.main.check_database",
        fail_check,
    )
    client = TestClient(app)

    response = client.get("/health/db")

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "database": "unreachable",
    }
    assert "super-secret" not in response.text
