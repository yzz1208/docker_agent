from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from docker_agent.config import get_settings


def create_db_engine() -> Engine:
    """Create a SQLAlchemy engine from application settings.

    The default local URL points to SQLite, which lets the project run
    without Docker. Later we can change DATABASE_URL to PostgreSQL/pgvector
    while keeping the rest of the application unchanged.
    """

    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True)


def check_database(engine: Engine | None = None) -> bool:
    """Return True when the configured database accepts a simple query."""

    engine = engine or create_db_engine()
    with engine.connect() as connection:
        return connection.execute(text("SELECT 1")).scalar_one() == 1
