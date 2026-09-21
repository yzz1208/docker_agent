import logging
from functools import lru_cache
from time import perf_counter
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from docker_agent.agent.configuration import (
    AgentConfigurationResolutionError,
    AgentDisabledError,
    require_enabled,
    resolve_docker_support_configuration,
    resolve_docker_support_settings,
)
from docker_agent.agent.router import AgentRoutingError
from docker_agent.agent.service import DockerSupportAgent
from docker_agent.api.agent_configurations import (
    AgentConfigurationCreateRequest,
    AgentConfigurationResponse,
    AgentConfigurationUpdateRequest,
    EffectiveAgentConfigurationResponse,
    build_agent_configuration_response,
    build_effective_agent_configuration_response,
)
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
from docker_agent.api.evaluations import (
    EvaluationComparisonResponse,
    EvaluationRunDetailResponse,
    EvaluationRunResponse,
    build_evaluation_case_response,
    build_evaluation_comparison_response,
    build_evaluation_run_response,
)
from docker_agent.api.operations import (
    AgentRunResponse,
    AgentRunStatusQuery,
    AgentRunSummaryResponse,
    build_agent_run_response,
    build_agent_run_summary_response,
)
from docker_agent.config import get_settings
from docker_agent.db import check_database, create_db_engine
from docker_agent.evaluation_comparison import (
    EvaluationComparisonError,
    compare_evaluation_runs,
)
from docker_agent.graph.service import LangGraphDockerSupportAgent
from docker_agent.observability import (
    configure_structured_logging,
    correlation_context,
    metrics,
    resolve_request_id,
)
from docker_agent.persistence import (
    AgentConfigurationAlreadyExists,
    AgentConfigurationNotFound,
    AgentRunNotFound,
    ChatConversationMismatch,
    ConversationAgentTypeMismatch,
    ConversationNotFound,
    EvaluationRunNotFound,
    PersistentChatCoordinator,
    create_agent_configuration,
    delete_conversation,
    get_agent_configuration,
    get_agent_run,
    get_evaluation_run,
    init_persistence_store,
    list_agent_configurations,
    list_agent_runs,
    list_conversations,
    list_evaluation_cases,
    list_evaluation_runs,
    load_conversation,
    rename_conversation,
    summarize_agent_runs,
    update_agent_configuration,
    validate_agent_configuration_settings,
)
from docker_agent.rag.answer import CitationValidationError
from docker_agent.tools.docker_cli import DockerToolTimeout

settings = get_settings()
configure_structured_logging(settings.app_log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Docker technical support agent backend.",
)


@app.middleware("http")
async def observe_http_request(
    request: Request,
    call_next,
) -> Response:
    """Attach request correlation and emit bounded request metrics."""

    request_id = resolve_request_id(
        request.headers.get("X-Request-ID")
    )
    started = perf_counter()
    response_status = status.HTTP_500_INTERNAL_SERVER_ERROR

    with correlation_context(request_id=request_id):
        try:
            response = await call_next(request)
            response_status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            route = _request_route_template(request)
            duration_ms = max(
                0,
                round((perf_counter() - started) * 1000),
            )
            if request.url.path != "/metrics":
                metrics.record_http_request(
                    method=request.method,
                    route=route,
                    status_code=response_status,
                )
            logger.info(
                "HTTP request completed",
                extra={
                    "http_method": request.method,
                    "http_route": route,
                    "http_status": response_status,
                    "duration_ms": duration_ms,
                },
            )


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics() -> Response:
    """Expose bounded in-process metrics in Prometheus text format."""

    return Response(
        content=metrics.render_prometheus(),
        media_type="text/plain; version=0.0.4",
    )


@lru_cache
def get_agent() -> DockerSupportAgent:
    """Create the LangGraph agent from secure settings plus product preferences."""

    base_settings = get_settings()
    try:
        record = get_agent_configuration(
            get_persistence_engine(),
            "docker_support",
        )
    except AgentConfigurationNotFound:
        record = None

    effective = require_enabled(
        resolve_docker_support_configuration(
            base_settings,
            record,
        )
    )
    return LangGraphDockerSupportAgent(settings=effective.settings)


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
    "/agent-configurations",
    response_model=list[AgentConfigurationResponse],
    tags=["agent-configurations"],
)
def agent_configurations() -> list[AgentConfigurationResponse]:
    """List persisted agent configuration records."""

    try:
        records = list_agent_configurations(get_persistence_engine())
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL is unavailable.",
        ) from exc

    return [
        build_agent_configuration_response(record)
        for record in records
    ]


@app.get(
    "/agent-configurations/{agent_type}/effective",
    response_model=EffectiveAgentConfigurationResponse,
    tags=["agent-configurations"],
)
def effective_agent_configuration(
    agent_type: str,
) -> EffectiveAgentConfigurationResponse:
    """Resolve one agent's safe product preferences into runtime values."""

    normalized_agent_type = agent_type.strip()
    if normalized_agent_type != "docker_support":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Effective configuration is not supported for agent type "
                f"{normalized_agent_type!r}."
            ),
        )

    base_settings = get_settings()
    try:
        record = get_agent_configuration(
            get_persistence_engine(),
            normalized_agent_type,
        )
    except AgentConfigurationNotFound:
        record = None
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

    try:
        effective = resolve_docker_support_configuration(
            base_settings,
            record,
        )
    except AgentConfigurationResolutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Invalid effective agent configuration: {exc}",
        ) from exc

    return build_effective_agent_configuration_response(
        base=base_settings,
        effective=effective,
        record=record,
    )


@app.get(
    "/agent-configurations/{agent_type}",
    response_model=AgentConfigurationResponse,
    tags=["agent-configurations"],
)
def agent_configuration_detail(
    agent_type: str,
) -> AgentConfigurationResponse:
    """Load one persisted agent configuration."""

    try:
        record = get_agent_configuration(
            get_persistence_engine(),
            agent_type,
        )
    except AgentConfigurationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent configuration was not found.",
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

    return build_agent_configuration_response(record)


@app.post(
    "/agent-configurations",
    response_model=AgentConfigurationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["agent-configurations"],
)
def create_agent_configuration_endpoint(
    request: AgentConfigurationCreateRequest,
) -> AgentConfigurationResponse:
    """Create a product-facing agent configuration."""

    try:
        validate_agent_configuration_settings(
            model_settings=request.model_settings,
            retrieval_settings=request.retrieval_settings,
            runtime_settings=request.runtime_settings,
        )

        if request.agent_type.strip() == "docker_support":
            resolve_docker_support_settings(
                get_settings(),
                model_settings=request.model_settings,
                retrieval_settings=request.retrieval_settings,
                runtime_settings=request.runtime_settings,
            )

        record = create_agent_configuration(
            get_persistence_engine(),
            agent_type=request.agent_type,
            display_name=request.display_name,
            enabled=request.enabled,
            model_settings=request.model_settings,
            retrieval_settings=request.retrieval_settings,
            runtime_settings=request.runtime_settings,
        )
    except AgentConfigurationAlreadyExists as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent configuration already exists.",
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

    if record.agent_type == "docker_support":
        get_agent.cache_clear()

    return build_agent_configuration_response(record)


@app.patch(
    "/agent-configurations/{agent_type}",
    response_model=AgentConfigurationResponse,
    tags=["agent-configurations"],
)
def update_agent_configuration_endpoint(
    agent_type: str,
    request: AgentConfigurationUpdateRequest,
) -> AgentConfigurationResponse:
    """Partially update persisted agent preferences."""

    try:
        validate_agent_configuration_settings(
            model_settings=request.model_settings,
            retrieval_settings=request.retrieval_settings,
            runtime_settings=request.runtime_settings,
        )

        if agent_type.strip() == "docker_support":
            current = get_agent_configuration(
                get_persistence_engine(),
                agent_type,
            )
            resolve_docker_support_settings(
                get_settings(),
                model_settings=(
                    request.model_settings
                    if request.model_settings is not None
                    else current.model_settings
                ),
                retrieval_settings=(
                    request.retrieval_settings
                    if request.retrieval_settings is not None
                    else current.retrieval_settings
                ),
                runtime_settings=(
                    request.runtime_settings
                    if request.runtime_settings is not None
                    else current.runtime_settings
                ),
            )

        record = update_agent_configuration(
            get_persistence_engine(),
            agent_type,
            display_name=request.display_name,
            enabled=request.enabled,
            model_settings=request.model_settings,
            retrieval_settings=request.retrieval_settings,
            runtime_settings=request.runtime_settings,
        )
    except AgentConfigurationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent configuration was not found.",
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

    if record.agent_type == "docker_support":
        get_agent.cache_clear()

    return build_agent_configuration_response(record)


@app.get(
    "/operations/evaluations",
    response_model=list[EvaluationRunResponse],
    tags=["operations"],
)
def evaluation_runs(
    suite: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[EvaluationRunResponse]:
    """List persisted evaluation runs ordered by newest first."""

    try:
        records = list_evaluation_runs(
            get_persistence_engine(),
            suite=suite,
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

    return [build_evaluation_run_response(record) for record in records]


@app.get(
    "/operations/evaluations/compare",
    response_model=EvaluationComparisonResponse,
    tags=["operations"],
)
def compare_evaluations(
    baseline_id: str,
    candidate_id: str,
    max_regression: float = 0.02,
) -> EvaluationComparisonResponse:
    """Compare two compatible persisted evaluation runs."""

    try:
        comparison = compare_evaluation_runs(
            get_persistence_engine(),
            baseline_run_id=baseline_id,
            candidate_run_id=candidate_id,
            max_regression=max_regression,
        )
    except EvaluationRunNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation run was not found.",
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL is unavailable.",
        ) from exc
    except (EvaluationComparisonError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return build_evaluation_comparison_response(comparison)


@app.get(
    "/operations/evaluations/{evaluation_run_id}",
    response_model=EvaluationRunDetailResponse,
    tags=["operations"],
)
def evaluation_run_detail(
    evaluation_run_id: str,
) -> EvaluationRunDetailResponse:
    """Load one evaluation run with its persisted per-case results."""

    try:
        run = get_evaluation_run(
            get_persistence_engine(),
            evaluation_run_id,
        )
        cases = list_evaluation_cases(
            get_persistence_engine(),
            evaluation_run_id,
        )
    except EvaluationRunNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation run was not found.",
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

    return EvaluationRunDetailResponse(
        run=build_evaluation_run_response(run),
        cases=[build_evaluation_case_response(case) for case in cases],
    )


@app.get(
    "/operations/runs",
    response_model=list[AgentRunResponse],
    tags=["operations"],
)
def operation_runs(
    conversation_id: str | None = None,
    agent_type: str | None = None,
    run_status: Annotated[
        AgentRunStatusQuery | None,
        Query(alias="status"),
    ] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AgentRunResponse]:
    """List safe Agent run telemetry ordered by newest first."""

    try:
        records = list_agent_runs(
            get_persistence_engine(),
            conversation_id=conversation_id,
            agent_type=agent_type,
            status=run_status,
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

    return [build_agent_run_response(record) for record in records]


@app.get(
    "/operations/runs/{run_id}",
    response_model=AgentRunResponse,
    tags=["operations"],
)
def operation_run_detail(run_id: str) -> AgentRunResponse:
    """Load one safe Agent run telemetry record."""

    try:
        record = get_agent_run(
            get_persistence_engine(),
            run_id,
        )
    except AgentRunNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent run was not found.",
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

    return build_agent_run_response(record)


@app.get(
    "/operations/summary",
    response_model=AgentRunSummaryResponse,
    tags=["operations"],
)
def operations_summary(
    hours: int = 24,
) -> AgentRunSummaryResponse:
    """Summarize Agent runs over a bounded recent time window."""

    try:
        summary = summarize_agent_runs(
            get_persistence_engine(),
            hours=hours,
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

    return build_agent_run_summary_response(summary)


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
def chat(
    request: ChatRequest,
    response: Response,
) -> ChatResponse:
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
    except AgentDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except AgentConfigurationResolutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Invalid effective agent configuration: {exc}",
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

    response.headers["X-Run-ID"] = turn.run.id
    response.headers["X-Conversation-ID"] = turn.conversation.id

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


def _request_route_template(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route_path, str) and route_path:
        return route_path
    return "unmatched"
