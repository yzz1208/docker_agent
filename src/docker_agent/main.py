from functools import lru_cache

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.engine import Engine
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
from docker_agent.api.conversations import (
    ConversationDetailResponse,
    ConversationRenameRequest,
    ConversationSummaryResponse,
    build_conversation_detail,
    build_conversation_summary,
)
from docker_agent.config import get_settings
from docker_agent.db import check_database, create_db_engine
from docker_agent.graph.service import LangGraphDockerSupportAgent
from docker_agent.persistence import (
    ChatConversationMismatch,
    ConversationAgentTypeMismatch,
    ConversationNotFound,
    PersistentChatCoordinator,
    delete_conversation,
    init_persistence_store,
    list_conversations,
    load_conversation,
    rename_conversation,
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
def get_persistence_engine() -> Engine:
    """Create the product persistence engine and tables lazily."""

    engine = create_db_engine(register_pgvector_types=False)
    init_persistence_store(engine)
    return engine


@lru_cache
def get_chat_coordinator() -> PersistentChatCoordinator:
    """Create the durable chat coordinator lazily."""

    return PersistentChatCoordinator(
        engine=get_persistence_engine(),
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





@app.get(
    "/conversations",
    response_model=list[ConversationSummaryResponse],
    tags=["conversations"],
)
def conversations(
    limit: int = 50,
    offset: int = 0,
) -> list[ConversationSummaryResponse]:
    """List durable conversations ordered by most recently updated."""

    try:
        records = list_conversations(
            get_persistence_engine(),
            limit=limit,
            offset=offset,
        )
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

    return [build_conversation_summary(record) for record in records]


@app.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailResponse,
    tags=["conversations"],
)
def conversation_detail(conversation_id: str) -> ConversationDetailResponse:
    """Load one durable conversation with messages and execution metadata."""

    try:
        snapshot = load_conversation(
            get_persistence_engine(),
            conversation_id,
        )
    except ConversationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation was not found.",
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

    return build_conversation_detail(snapshot)

@app.patch(
    "/conversations/{conversation_id}",
    response_model=ConversationSummaryResponse,
    tags=["conversations"],
)
def rename_conversation_endpoint(
    conversation_id: str,
    request: ConversationRenameRequest,
) -> ConversationSummaryResponse:
    """Rename one durable conversation."""

    try:
        record = rename_conversation(
            get_persistence_engine(),
            conversation_id,
            title=request.title,
        )
    except ConversationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation was not found.",
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

    return build_conversation_summary(record)


@app.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["conversations"],
)
def delete_conversation_endpoint(conversation_id: str) -> Response:
    """Delete one durable conversation and its persisted history."""

    try:
        get_chat_coordinator().reset_conversation_sessions(conversation_id)
        delete_conversation(
            get_persistence_engine(),
            conversation_id,
        )
    except ConversationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation was not found.",
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

    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
