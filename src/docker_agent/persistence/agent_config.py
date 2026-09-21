from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from docker_agent.persistence.models import AgentConfiguration, utc_now

_SECRET_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "client_secret",
    "credential",
    "credentials",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "token",
}


@dataclass(frozen=True, slots=True)
class AgentConfigurationRecord:
    agent_type: str
    display_name: str
    enabled: bool
    model_settings: dict[str, object]
    retrieval_settings: dict[str, object]
    runtime_settings: dict[str, object]
    created_at: datetime
    updated_at: datetime


class AgentConfigurationNotFound(KeyError):
    """Raised when an agent configuration does not exist."""


class AgentConfigurationAlreadyExists(ValueError):
    """Raised when trying to create a duplicate agent configuration."""


def create_agent_configuration(
    engine: Engine,
    *,
    agent_type: str,
    display_name: str,
    enabled: bool = True,
    model_settings: dict[str, object] | None = None,
    retrieval_settings: dict[str, object] | None = None,
    runtime_settings: dict[str, object] | None = None,
) -> AgentConfigurationRecord:
    normalized_agent_type = _normalize_agent_type(agent_type)
    normalized_display_name = _normalize_display_name(display_name)
    model = _validated_settings(model_settings, field_name="model_settings")
    retrieval = _validated_settings(
        retrieval_settings,
        field_name="retrieval_settings",
    )
    runtime = _validated_settings(
        runtime_settings,
        field_name="runtime_settings",
    )

    row = AgentConfiguration(
        agent_type=normalized_agent_type,
        display_name=normalized_display_name,
        enabled=enabled,
        model_settings=model,
        retrieval_settings=retrieval,
        runtime_settings=runtime,
    )
    with Session(engine) as session:
        session.add(row)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise AgentConfigurationAlreadyExists(
                normalized_agent_type
            ) from exc
        session.refresh(row)
        return _agent_configuration_record(row)


def get_agent_configuration(
    engine: Engine,
    agent_type: str,
) -> AgentConfigurationRecord:
    normalized_agent_type = _normalize_agent_type(agent_type)

    with Session(engine) as session:
        row = session.get(AgentConfiguration, normalized_agent_type)
        if row is None:
            raise AgentConfigurationNotFound(normalized_agent_type)
        return _agent_configuration_record(row)


def list_agent_configurations(
    engine: Engine,
) -> tuple[AgentConfigurationRecord, ...]:
    statement = select(AgentConfiguration).order_by(
        AgentConfiguration.display_name,
        AgentConfiguration.agent_type,
    )
    with Session(engine) as session:
        rows = session.scalars(statement).all()
        return tuple(_agent_configuration_record(row) for row in rows)


def update_agent_configuration(
    engine: Engine,
    agent_type: str,
    *,
    display_name: str | None = None,
    enabled: bool | None = None,
    model_settings: dict[str, object] | None = None,
    retrieval_settings: dict[str, object] | None = None,
    runtime_settings: dict[str, object] | None = None,
) -> AgentConfigurationRecord:
    normalized_agent_type = _normalize_agent_type(agent_type)

    with Session(engine) as session:
        row = session.get(AgentConfiguration, normalized_agent_type)
        if row is None:
            raise AgentConfigurationNotFound(normalized_agent_type)

        if display_name is not None:
            row.display_name = _normalize_display_name(display_name)
        if enabled is not None:
            row.enabled = enabled
        if model_settings is not None:
            row.model_settings = _validated_settings(
                model_settings,
                field_name="model_settings",
            )
        if retrieval_settings is not None:
            row.retrieval_settings = _validated_settings(
                retrieval_settings,
                field_name="retrieval_settings",
            )
        if runtime_settings is not None:
            row.runtime_settings = _validated_settings(
                runtime_settings,
                field_name="runtime_settings",
            )

        row.updated_at = utc_now()
        session.commit()
        session.refresh(row)
        return _agent_configuration_record(row)


def _normalize_agent_type(agent_type: str) -> str:
    normalized = agent_type.strip()
    if not normalized:
        raise ValueError("agent_type must not be empty")
    if len(normalized) > 64:
        raise ValueError("agent_type must not exceed 64 characters")
    return normalized


def _normalize_display_name(display_name: str) -> str:
    normalized = display_name.strip()
    if not normalized:
        raise ValueError("display_name must not be empty")
    if len(normalized) > 120:
        raise ValueError("display_name must not exceed 120 characters")
    return normalized


def _validated_settings(
    settings: dict[str, object] | None,
    *,
    field_name: str,
) -> dict[str, object]:
    if settings is None:
        return {}

    copied = deepcopy(settings)
    _reject_secret_fields(copied, path=field_name)
    return copied


def _reject_secret_fields(value: object, *, path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key).strip().lower().replace("-", "_")
            if normalized_key in _SECRET_KEYS:
                raise ValueError(
                    f"{path} must not contain secret field {key!r}"
                )
            _reject_secret_fields(child, path=f"{path}.{key}")
        return

    if isinstance(value, list | tuple):
        for index, child in enumerate(value):
            _reject_secret_fields(child, path=f"{path}[{index}]")


def _agent_configuration_record(
    row: AgentConfiguration,
) -> AgentConfigurationRecord:
    return AgentConfigurationRecord(
        agent_type=row.agent_type,
        display_name=row.display_name,
        enabled=row.enabled,
        model_settings=deepcopy(row.model_settings),
        retrieval_settings=deepcopy(row.retrieval_settings),
        runtime_settings=deepcopy(row.runtime_settings),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
