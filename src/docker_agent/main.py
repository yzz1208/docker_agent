from functools import lru_cache

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from docker_agent.agent.router import AgentRoutingError
from docker_agent.agent.service import DockerSupportAgent
from docker_agent.api.chat import (
    ChatRequest,
    ChatResponse,
    ChatSessionManager,
    ChatSessionNotFound,
    build_chat_response,
)
from docker_agent.config import get_settings
from docker_agent.db import check_database
from docker_agent.rag.answer import CitationValidationError
from docker_agent.tools.docker_cli import DockerToolTimeout

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Docker technical support agent backend.",
)


@lru_cache
def get_agent() -> DockerSupportAgent:
    """Create the expensive agent stack lazily on the first chat request."""

    return DockerSupportAgent()


chat_sessions = ChatSessionManager(agent_factory=get_agent)


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


@app.post("/chat", response_model=ChatResponse, tags=["agent"])
def chat(request: ChatRequest) -> ChatResponse:
    """Run one agent turn, optionally continuing a pending clarification session."""

    try:
        session_id, active, result = chat_sessions.chat(
            message=request.message,
            session_id=request.session_id,
        )
    except ChatSessionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session was not found or has already completed.",
        ) from exc
    except AgentRoutingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsafe or invalid route decision: {exc}",
        ) from exc
    except CitationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Invalid model citation: {exc}",
        ) from exc
    except DockerToolTimeout as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(exc),
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL is unavailable.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return build_chat_response(session_id, active, result)


@app.delete(
    "/chat/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["agent"],
)
def reset_chat_session(session_id: str) -> Response:
    """Discard a pending clarification session."""

    try:
        removed = chat_sessions.reset(session_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session was not found.",
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
