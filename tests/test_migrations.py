from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from docker_agent.config import get_settings
from docker_agent.persistence.models import PersistenceBase

_PRODUCT_TABLES = {
    "agent_configurations",
    "conversations",
    "messages",
    "agent_executions",
    "agent_runs",
    "evaluation_runs",
    "evaluation_case_results",
}


def _alembic_config(database_url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url",
        database_url.replace("%", "%%"),
    )
    return config


def test_migrations_upgrade_match_metadata_and_round_trip(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "migration-test.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()

    try:
        config = _alembic_config(database_url)

        command.upgrade(config, "head")

        engine = create_engine(database_url)
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())

        assert _PRODUCT_TABLES <= table_names
        assert "alembic_version" in table_names

        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            differences = compare_metadata(
                context,
                PersistenceBase.metadata,
            )

        assert differences == []

        command.downgrade(config, "base")

        downgraded_tables = set(inspect(engine).get_table_names())
        assert _PRODUCT_TABLES.isdisjoint(downgraded_tables)
        assert "alembic_version" in downgraded_tables

        command.upgrade(config, "head")

        upgraded_again = set(inspect(engine).get_table_names())
        assert _PRODUCT_TABLES <= upgraded_again
        assert "alembic_version" in upgraded_again

        engine.dispose()
    finally:
        get_settings.cache_clear()
