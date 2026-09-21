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
from docker_agent.db import check_database, create_db_engine
from docker_agent.graph.service import LangGraphDockerSupportAgent
from docker_agent.persistence import (
    ChatConversationMismatch,
    ConversationAgentTypeMismatch,
    ConversationNotFound,
    PersistentChatCoordinator,
    init_persistence_store,
)
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
    """Create the LangGraph-backed agent stack lazily on first use."""

    return LangGraphDockerSupportAgent()


chat_sessions = ChatSessionManager(agent_factory=get_agent)


@lru_cache
def get_chat_coordinator() -> PersistentChatCoordinator:
    """Create the durable chat coordinator and product tables lazily."""

    engine = create_db_engine(register_pgvector_types=False)
    init_persistence_store(engine)
    return PersistentChatCoordinator(
        engine=engine,
        sessions=chat_sessions,
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


@app.post("/chat", response_model=ChatResponse, tags=["agent"])
def chat(request: ChatRequest) -> ChatResponse:
    """Run and persist one product chat turn."""

    try:
        turn = get_chat_coordinator().chat(
            message=request.message,
            conversation_id=request.conversation_id,
            session_id=request.session_id,
        )
    except (ChatSessionNotFound, ConversationNotFound) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation or chat session was not found.",
        ) from exc
    except (ChatConversationMismatch, ConversationAgentTypeMismatch) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
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

    return build_chat_response(
        turn.session_id,
        turn.session_active,
        turn.result,
        conversation_id=turn.conversation.id,
    )


@app.delete(
    "/chat/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["agent"],
)
def reset_chat_session(session_id: str) -> Response:
    """Discard clarification state without deleting conversation history."""

    try:
        removed = get_chat_coordinator().reset(session_id)
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
