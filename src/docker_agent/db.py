from pgvector.psycopg import register_vector
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

from docker_agent.config import get_settings


def create_db_engine(*, register_pgvector_types: bool = True) -> Engine:
    """Create a SQLAlchemy engine from application settings.

    PostgreSQL is the project's primary database. When pgvector types are needed,
    register them on each psycopg connection so vector columns can be read and written
    as Python lists.
    """

    settings = get_settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True)

    if register_pgvector_types and settings.database_url.startswith("postgresql"):

        @event.listens_for(engine, "connect")
        def _register_vector_types(dbapi_connection: object, _connection_record: object) -> None:
            register_vector(dbapi_connection)

    return engine


def check_database(engine: Engine | None = None) -> bool:
    """Return True when the configured database accepts a simple query."""

    engine = engine or create_db_engine(register_pgvector_types=False)
    with engine.connect() as connection:
        return connection.execute(text("SELECT 1")).scalar_one() == 1
