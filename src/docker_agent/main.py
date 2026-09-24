import json
import logging
from collections.abc import Iterator
from contextlib import asynccontextmanager
from functools import lru_cache
from queue import Empty, Queue
from threading import Thread
from time import perf_counter
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from psycopg import Error as PsycopgError
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from docker_agent.agent.configuration import (
    AgentConfigurationResolutionError,
    AgentDisabledError,
    require_enabled,
    resolve_agent_configuration,
    resolve_docker_support_configuration,
)
from docker_agent.agent.configuration_schema import (
    ConfigurationSchemaError,
    resolve_settings_from_schema,
)
from docker_agent.agent.factory import (
    AgentFactory,
    AgentProtocol,
    validate_factory_registration,
)
from docker_agent.agent.infrastructure import (
    InfrastructureTroubleshooterAgent,
)
from docker_agent.agent.registry import (
    DOCKER_SUPPORT_DESCRIPTOR,
    INFRASTRUCTURE_TROUBLESHOOTER_DESCRIPTOR,
    AgentNotRegistered,
    AgentRegistryError,
    build_agent_registry,
)
from docker_agent.agent.router import AgentRoutingError
from docker_agent.api.agent_configurations import (
    AgentConfigurationCreateRequest,
    AgentConfigurationResponse,
    AgentConfigurationUpdateRequest,
    EffectiveAgentConfigurationResponse,
    build_agent_configuration_response,
    build_effective_agent_configuration_response,
)
from docker_agent.api.agents import (
    AgentDescriptorResponse,
    build_agent_descriptor_response,
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
from docker_agent.api.orchestration import (
    AutoApprovalDecisionRequest,
    AutoChatRequest,
    AutoChatResponse,
    build_auto_chat_response,
)
from docker_agent.config import (
    get_settings,
    require_application_runtime_settings,
)
from docker_agent.db import (
    check_database,
    create_db_engine,
    get_database_readiness,
    require_database_ready,
)
from docker_agent.evaluation_comparison import (
    EvaluationComparisonError,
    compare_evaluation_runs,
)
from docker_agent.graph.service import LangGraphDockerSupportAgent
from docker_agent.observability import (
    StageEvent,
    configure_structured_logging,
    correlation_context,
    current_correlation,
    metrics,
    resolve_request_id,
    stage_event_context,
)
from docker_agent.orchestration import (
    AutoOrchestrationError,
    DelegationExecutionService,
    LangGraphProductAutoOrchestrationService,
    OrchestratedSynthesisService,
    OrchestrationDecisionError,
    OrchestrationDecisionModel,
    OrchestrationExecutionError,
    OrchestrationSynthesisError,
    open_postgres_orchestration_checkpointer,
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
    get_conversation,
    get_evaluation_run,
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
from docker_agent.rag.llm import (
    ModelRequestError,
    ModelResponseError,
    OpenAICompatibleChatClient,
)
from docker_agent.tools.docker_cli import DockerToolTimeout

settings = get_settings()
configure_structured_logging(settings.app_log_level)
logger = logging.getLogger(__name__)
agent_registry = build_agent_registry()
runtime_agent_factory = AgentFactory(registry=agent_registry)


def _build_docker_support_agent() -> AgentProtocol:
    base_settings = get_settings()
    try:
        record = get_agent_configuration(
            get_persistence_engine(),
            DOCKER_SUPPORT_DESCRIPTOR.agent_type,
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


runtime_agent_factory.register(
    DOCKER_SUPPORT_DESCRIPTOR.agent_type,
    _build_docker_support_agent,
)


def _build_infrastructure_troubleshooter() -> AgentProtocol:
    descriptor = INFRASTRUCTURE_TROUBLESHOOTER_DESCRIPTOR
    base_settings = get_settings()
    try:
        record = get_agent_configuration(
            get_persistence_engine(),
            descriptor.agent_type,
        )
    except AgentConfigurationNotFound:
        record = None

    effective = require_enabled(
        resolve_agent_configuration(
            descriptor,
            base_settings,
            record,
        )
    )
    return InfrastructureTroubleshooterAgent(
        settings=effective.settings
    )


runtime_agent_factory.register(
    INFRASTRUCTURE_TROUBLESHOOTER_DESCRIPTOR.agent_type,
    _build_infrastructure_troubleshooter,
)
validate_factory_registration(
    registry=agent_registry,
    factory=runtime_agent_factory,
)


def _warm_rag_models(agent: AgentProtocol) -> None:
    """Preload heavyweight retrieval models without blocking app startup."""

    warmup = getattr(agent, "warmup_retrieval", None)
    if not callable(warmup):
        logger.warning(
            "RAG model warmup skipped because the Agent has no warmup hook"
        )
        return

    started = perf_counter()
    logger.info("RAG model warmup started")
    try:
        warmup()
    except Exception:
        logger.exception("RAG model warmup failed")
        return

    logger.info(
        "RAG model warmup completed",
        extra={
            "duration_ms": max(
                0,
                round((perf_counter() - started) * 1000),
            ),
        },
    )


@asynccontextmanager
async def app_lifespan(_app: FastAPI):
    """Own runtime validation, database readiness, and engine disposal."""

    require_application_runtime_settings(settings)
    engine = get_persistence_engine()
    try:
        readiness = require_database_ready(engine)
        logger.info(
            "Application database is ready",
            extra={
                "database_schema_current": readiness.schema_current,
                "database_revision": ",".join(
                    readiness.current_revisions
                ),
            },
        )

        if settings.rag_warmup_on_startup:
            docker_support = get_agent(
                DOCKER_SUPPORT_DESCRIPTOR.agent_type
            )
            Thread(
                target=_warm_rag_models,
                args=(docker_support,),
                name="docker-agent-rag-warmup",
                daemon=True,
            ).start()

        yield
    finally:
        get_chat_coordinator.cache_clear()
        get_chat_sessions.cache_clear()
        get_auto_orchestration_service.cache_clear()
        get_agent.cache_clear()
        runtime_agent_factory.clear()
        engine.dispose()
        get_persistence_engine.cache_clear()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Docker technical support agent backend.",
    lifespan=app_lifespan,
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
def get_agent(
    agent_type: str = DOCKER_SUPPORT_DESCRIPTOR.agent_type,
) -> AgentProtocol:
    """Return one cached runtime Agent by registered Agent type."""

    descriptor = agent_registry.get(agent_type)
    return runtime_agent_factory.get(descriptor.agent_type)


@lru_cache
def get_chat_sessions(
    agent_type: str = DOCKER_SUPPORT_DESCRIPTOR.agent_type,
) -> ChatSessionManager:
    """Return clarification-session state isolated by Agent type."""

    descriptor = agent_registry.get(agent_type)
    canonical = descriptor.agent_type
    return ChatSessionManager(
        agent_factory=lambda: get_agent(canonical),
        agent_type=canonical,
    )


@lru_cache
def get_persistence_engine() -> Engine:
    """Create the product persistence engine.

    Product schema creation and upgrades are owned by Alembic migrations.
    """

    return create_db_engine(register_pgvector_types=False)


@lru_cache
def get_chat_coordinator(
    agent_type: str = DOCKER_SUPPORT_DESCRIPTOR.agent_type,
) -> PersistentChatCoordinator:
    """Return one durable chat coordinator isolated by Agent type."""

    descriptor = agent_registry.get(agent_type)
    canonical = descriptor.agent_type
    return PersistentChatCoordinator(
        engine=get_persistence_engine(),
        sessions=get_chat_sessions(canonical),
        agent_type=canonical,
    )


def _orchestration_model(
    *,
    temperature: float,
    max_tokens: int,
) -> OpenAICompatibleChatClient:
    current = get_settings()
    if not current.model_name.strip() or not current.model_base_url.strip():
        raise ValueError(
            "MODEL_NAME and MODEL_BASE_URL must be configured"
        )
    configured_tokens = current.model_max_tokens
    token_limit = (
        min(configured_tokens, max_tokens)
        if configured_tokens is not None
        else max_tokens
    )
    return OpenAICompatibleChatClient(
        model=current.model_name,
        base_url=current.model_base_url,
        api_key=current.model_api_key,
        timeout_seconds=current.model_timeout_seconds,
        temperature=temperature,
        max_tokens=token_limit,
        max_retries=current.model_max_retries,
        retry_backoff_seconds=current.model_retry_backoff_seconds,
    )


@lru_cache
def get_auto_orchestration_service() -> LangGraphProductAutoOrchestrationService:
    """Build the Phase 9 LangGraph product auto-orchestration runtime."""

    decision = OrchestrationDecisionModel(
        registry=agent_registry,
        model=_orchestration_model(
            temperature=0.0,
            max_tokens=320,
        ),
        max_hops=2,
    )
    execution = DelegationExecutionService(
        registry=agent_registry,
        factory=runtime_agent_factory,
        max_hops=2,
    )
    synthesis = OrchestratedSynthesisService(
        model=_orchestration_model(
            temperature=0.1,
            max_tokens=1200,
        ),
    )
    return LangGraphProductAutoOrchestrationService(
        engine=get_persistence_engine(),
        decision_model=decision,
        execution_service=execution,
        synthesis_service=synthesis,
        checkpointer_context_factory=(
            open_postgres_orchestration_checkpointer
        ),
    )


@app.get(
    "/agents",
    response_model=list[AgentDescriptorResponse],
    tags=["agents"],
)
def registered_agents() -> list[AgentDescriptorResponse]:
    """List runtime-supported Agent descriptors."""

    return [
        build_agent_descriptor_response(descriptor)
        for descriptor in agent_registry.list()
    ]


@app.get(
    "/agents/{agent_type}",
    response_model=AgentDescriptorResponse,
    tags=["agents"],
)
def registered_agent_detail(
    agent_type: str,
) -> AgentDescriptorResponse:
    """Load one runtime-supported Agent descriptor."""

    try:
        descriptor = agent_registry.get(agent_type)
    except AgentNotRegistered as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent type is not registered.",
        ) from exc
    except AgentRegistryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return build_agent_descriptor_response(descriptor)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Basic liveness endpoint that does not depend on external services."""

    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}


@app.get("/health/db", tags=["system"])
def database_health() -> JSONResponse:
    """Check whether the configured database is reachable."""

    try:
        healthy = check_database(get_persistence_engine())
    except SQLAlchemyError:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "error",
                "database": "unreachable",
            },
        )

    return JSONResponse(
        status_code=(
            status.HTTP_200_OK
            if healthy
            else status.HTTP_503_SERVICE_UNAVAILABLE
        ),
        content={
            "status": "ok" if healthy else "error",
            "database": "reachable" if healthy else "unreachable",
        },
    )


@app.get("/health/ready", tags=["system"])
def readiness_health() -> JSONResponse:
    """Check database connectivity and Alembic schema readiness."""

    try:
        readiness = get_database_readiness(
            get_persistence_engine()
        )
    except SQLAlchemyError:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "error",
                "database": "unreachable",
                "schema": "unknown",
            },
        )

    if not readiness.schema_current:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "error",
                "database": "reachable",
                "schema": "outdated",
                "current_revisions": list(
                    readiness.current_revisions
                ),
                "head_revisions": list(readiness.head_revisions),
            },
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "ok",
            "database": "reachable",
            "schema": "current",
            "current_revisions": list(readiness.current_revisions),
            "head_revisions": list(readiness.head_revisions),
        },
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
    except (SQLAlchemyError, PsycopgError) as exc:
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

    try:
        descriptor = agent_registry.get(agent_type)
    except AgentRegistryError as exc:
        normalized_agent_type = agent_type.strip()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Effective configuration is not supported for agent type "
                f"{normalized_agent_type!r}."
            ),
        ) from exc

    normalized_agent_type = descriptor.agent_type
    base_settings = get_settings()
    try:
        record = get_agent_configuration(
            get_persistence_engine(),
            normalized_agent_type,
        )
    except AgentConfigurationNotFound:
        record = None
    except (SQLAlchemyError, PsycopgError) as exc:
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
        effective = resolve_agent_configuration(
            descriptor,
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
        descriptor=descriptor,
    )


def _configuration_agent_type(agent_type: str) -> str:
    try:
        return agent_registry.get(agent_type).agent_type
    except AgentNotRegistered:
        return agent_type


def _invalidate_registered_agent_runtime(agent_type: str) -> None:
    if agent_type not in runtime_agent_factory.registered_types():
        return
    runtime_agent_factory.invalidate(agent_type)
    get_agent.cache_clear()


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
            _configuration_agent_type(agent_type),
        )
    except AgentConfigurationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent configuration was not found.",
        ) from exc
    except (SQLAlchemyError, PsycopgError) as exc:
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


def _validate_registered_agent_preferences(
    *,
    agent_type: str,
    model_settings: dict[str, object],
    retrieval_settings: dict[str, object],
    runtime_settings: dict[str, object],
) -> None:
    try:
        descriptor = agent_registry.get(agent_type)
    except AgentNotRegistered:
        return

    try:
        resolve_settings_from_schema(
            get_settings(),
            schema=descriptor.configuration_schema,
            rules=descriptor.configuration_rules,
            model_settings=model_settings,
            retrieval_settings=retrieval_settings,
            runtime_settings=runtime_settings,
        )
    except ConfigurationSchemaError as exc:
        raise ValueError(str(exc)) from exc


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

        _validate_registered_agent_preferences(
            agent_type=request.agent_type,
            model_settings=request.model_settings,
            retrieval_settings=request.retrieval_settings,
            runtime_settings=request.runtime_settings,
        )

        record = create_agent_configuration(
            get_persistence_engine(),
            agent_type=_configuration_agent_type(
                request.agent_type
            ),
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
    except (SQLAlchemyError, PsycopgError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL is unavailable.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    _invalidate_registered_agent_runtime(record.agent_type)

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

        try:
            descriptor = agent_registry.get(agent_type)
        except AgentNotRegistered:
            descriptor = None

        if descriptor is not None:
            current = get_agent_configuration(
                get_persistence_engine(),
                descriptor.agent_type,
            )
            _validate_registered_agent_preferences(
                agent_type=descriptor.agent_type,
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
            _configuration_agent_type(agent_type),
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
    except (SQLAlchemyError, PsycopgError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL is unavailable.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    _invalidate_registered_agent_runtime(record.agent_type)

    return build_agent_configuration_response(record)


@app.get(
    "/operations/evaluations",
    response_model=list[EvaluationRunResponse],
    tags=["operations"],
)
def evaluation_runs(
    suite: str | None = None,
    agent_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[EvaluationRunResponse]:
    """List persisted evaluation runs ordered by newest first."""

    try:
        records = list_evaluation_runs(
            get_persistence_engine(),
            suite=suite,
            agent_type=agent_type,
            limit=limit,
            offset=offset,
        )
    except (SQLAlchemyError, PsycopgError) as exc:
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
    except (SQLAlchemyError, PsycopgError) as exc:
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
    except (SQLAlchemyError, PsycopgError) as exc:
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
    except (SQLAlchemyError, PsycopgError) as exc:
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
    except (SQLAlchemyError, PsycopgError) as exc:
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
    agent_type: str | None = None,
) -> AgentRunSummaryResponse:
    """Summarize Agent runs over a bounded recent time window."""

    try:
        summary = summarize_agent_runs(
            get_persistence_engine(),
            hours=hours,
            agent_type=agent_type,
        )
    except (SQLAlchemyError, PsycopgError) as exc:
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
    except (SQLAlchemyError, PsycopgError) as exc:
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
    except (SQLAlchemyError, PsycopgError) as exc:
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
    except (SQLAlchemyError, PsycopgError) as exc:
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
    except (SQLAlchemyError, PsycopgError) as exc:
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


def _resolve_chat_agent_type(
    request: ChatRequest,
) -> str:
    if request.conversation_id is None:
        requested = (
            request.agent_type
            or DOCKER_SUPPORT_DESCRIPTOR.agent_type
        )
        return agent_registry.get(requested).agent_type

    conversation_id = request.conversation_id.strip()
    if not conversation_id:
        raise ValueError("conversation_id must not be empty")

    conversation = get_conversation(
        get_persistence_engine(),
        conversation_id,
    )
    descriptor = agent_registry.get(conversation.agent_type)

    if request.agent_type is None:
        return descriptor.agent_type

    requested = agent_registry.get(request.agent_type)
    if requested.agent_type != descriptor.agent_type:
        raise ConversationAgentTypeMismatch(
            f"conversation agent_type={descriptor.agent_type!r} "
            f"does not match requested agent_type="
            f"{requested.agent_type!r}"
        )

    return descriptor.agent_type


def _auto_stream_error_message(error: BaseException) -> str:
    if isinstance(error, ConversationNotFound):
        return "对话不存在。"
    if isinstance(error, AgentDisabledError):
        return str(error)
    if isinstance(
        error,
        (
            AutoOrchestrationError,
            OrchestrationDecisionError,
            OrchestrationExecutionError,
            OrchestrationSynthesisError,
            AgentRegistryError,
        ),
    ):
        return str(error)
    if isinstance(error, (ModelRequestError, ModelResponseError)):
        return "编排模型请求失败，请稍后重试。"
    if isinstance(error, (SQLAlchemyError, PsycopgError)):
        return "PostgreSQL 暂时不可用。"
    if isinstance(error, ValueError):
        return str(error)
    return "智能编排执行失败，请稍后重试。"


def _encode_sse_event(
    event_name: str,
    payload: dict[str, object],
) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"event: {event_name}\ndata: {encoded}\n\n"


def _auto_stream_events(
    event_queue: Queue[tuple[str, dict[str, object]] | None],
) -> Iterator[str]:
    while True:
        try:
            item = event_queue.get(timeout=15)
        except Empty:
            yield ": keep-alive\n\n"
            continue

        if item is None:
            return
        event_name, payload = item
        yield _encode_sse_event(event_name, payload)


@app.post(
    "/chat/auto/stream",
    response_class=StreamingResponse,
    tags=["agent"],
)
def auto_chat_stream(
    request: AutoChatRequest,
) -> StreamingResponse:
    """Stream real execution progress followed by one final auto-chat result."""

    event_queue: Queue[
        tuple[str, dict[str, object]] | None
    ] = Queue()
    event_queue.put(
        (
            "progress",
            {
                "stage": "request",
                "status": "started",
                "duration_ms": None,
            },
        )
    )
    correlation = current_correlation()

    def emit_stage(event: StageEvent) -> None:
        event_queue.put(
            (
                "progress",
                {
                    "stage": event.stage,
                    "status": event.status,
                    "duration_ms": event.duration_ms,
                },
            )
        )

    def run_turn() -> None:
        try:
            with (
                correlation_context(
                    request_id=correlation.request_id,
                    run_id=correlation.run_id,
                    conversation_id=correlation.conversation_id,
                ),
                stage_event_context(emit_stage),
            ):
                turn = get_auto_orchestration_service().chat(
                    message=request.message,
                    conversation_id=request.conversation_id,
                )
            response = build_auto_chat_response(turn)
            event_queue.put(
                (
                    "result",
                    response.model_dump(mode="json"),
                )
            )
        except Exception as exc:
            logger.exception(
                "Auto chat stream failed",
                extra={"error_type": type(exc).__name__},
            )
            event_queue.put(
                (
                    "error",
                    {
                        "message": _auto_stream_error_message(exc),
                        "error_type": type(exc).__name__,
                    },
                )
            )
        finally:
            event_queue.put(None)

    Thread(
        target=run_turn,
        name="docker-agent-auto-stream",
        daemon=True,
    ).start()

    return StreamingResponse(
        _auto_stream_events(event_queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@app.post(
    "/chat/auto",
    response_model=AutoChatResponse,
    tags=["agent"],
)
def auto_chat(
    request: AutoChatRequest,
    response: Response,
) -> AutoChatResponse:
    """Run one bounded low-latency auto-orchestration turn."""

    try:
        turn = get_auto_orchestration_service().chat(
            message=request.message,
            conversation_id=request.conversation_id,
        )
    except ConversationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation was not found.",
        ) from exc
    except AgentDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (
        AutoOrchestrationError,
        OrchestrationDecisionError,
        OrchestrationExecutionError,
        OrchestrationSynthesisError,
        AgentRegistryError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except (ModelRequestError, ModelResponseError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Orchestration model failed: {exc}",
        ) from exc
    except (SQLAlchemyError, PsycopgError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL is unavailable.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    response.headers["X-Conversation-ID"] = turn.conversation.id
    response.headers["X-Agent-Type"] = "auto_orchestration"
    if turn.current_agent_type is not None:
        response.headers["X-Orchestration-Owner"] = (
            turn.current_agent_type
        )

    return build_auto_chat_response(turn)


@app.get(
    "/chat/auto/{conversation_id}/approval",
    response_model=AutoChatResponse | None,
    tags=["agent"],
)
def auto_chat_pending_approval(
    conversation_id: str,
) -> AutoChatResponse | None:
    """Return a pending durable approval for one auto conversation."""

    try:
        turn = get_auto_orchestration_service().pending_approval(
            conversation_id=conversation_id,
        )
    except ConversationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation was not found.",
        ) from exc
    except (
        AutoOrchestrationError,
        OrchestrationDecisionError,
        OrchestrationExecutionError,
        OrchestrationSynthesisError,
        AgentRegistryError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except (SQLAlchemyError, PsycopgError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL is unavailable.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return (
        build_auto_chat_response(turn)
        if turn is not None
        else None
    )


@app.post(
    "/chat/auto/{conversation_id}/approval",
    response_model=AutoChatResponse,
    tags=["agent"],
)
def resolve_auto_chat_approval(
    conversation_id: str,
    request: AutoApprovalDecisionRequest,
    response: Response,
) -> AutoChatResponse:
    """Approve or deny one pending LangGraph orchestration interrupt."""

    try:
        turn = get_auto_orchestration_service().resume_approval(
            conversation_id=conversation_id,
            approved=request.approved,
            comment=request.comment,
        )
    except ConversationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation was not found.",
        ) from exc
    except AgentDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (
        AutoOrchestrationError,
        OrchestrationDecisionError,
        OrchestrationExecutionError,
        OrchestrationSynthesisError,
        AgentRegistryError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except (ModelRequestError, ModelResponseError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Orchestration model failed: {exc}",
        ) from exc
    except (SQLAlchemyError, PsycopgError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL is unavailable.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    response.headers["X-Conversation-ID"] = turn.conversation.id
    response.headers["X-Agent-Type"] = "auto_orchestration"
    if turn.current_agent_type is not None:
        response.headers["X-Orchestration-Owner"] = (
            turn.current_agent_type
        )

    return build_auto_chat_response(turn)


@app.post("/chat", response_model=ChatResponse, tags=["agent"])
def chat(
    request: ChatRequest,
    response: Response,
) -> ChatResponse:
    """Run and persist one product chat turn."""

    try:
        agent_type = _resolve_chat_agent_type(request)
        turn = get_chat_coordinator(agent_type).chat(
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
    except AgentNotRegistered as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent type is not registered.",
        ) from exc
    except AgentRegistryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
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
    except (SQLAlchemyError, PsycopgError) as exc:
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
    response.headers["X-Agent-Type"] = turn.conversation.agent_type

    return build_chat_response(
        turn.session_id,
        turn.session_active,
        turn.result,
        agent_type=turn.conversation.agent_type,
        conversation_id=turn.conversation.id,
    )


@app.delete(
    "/chat/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["agent"],
)
def reset_chat_session(
    session_id: str,
    agent_type: str | None = None,
) -> Response:
    """Discard one Agent's clarification state without deleting history."""

    try:
        descriptor = agent_registry.get(
            agent_type or DOCKER_SUPPORT_DESCRIPTOR.agent_type
        )
        removed = get_chat_coordinator(
            descriptor.agent_type
        ).reset(session_id)
    except AgentRegistryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
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
