from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from docker_agent.config import get_settings
from docker_agent.db import check_database

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Docker technical support agent backend.",
)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Basic liveness endpoint that does not depend on external services."""

    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}


@app.get("/health/db", tags=["system"])
def database_health() -> JSONResponse:
    """Check whether the configured PostgreSQL instance is reachable."""

    try:
        healthy = check_database()
    except SQLAlchemyError as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "database": "unreachable", "detail": str(exc)},
        )

    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "error", "database": "reachable"},
    )
