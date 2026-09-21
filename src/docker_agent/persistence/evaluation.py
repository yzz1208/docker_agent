from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from docker_agent.observability import redact_log_text
from docker_agent.persistence.models import (
    EvaluationCaseResult,
    EvaluationRun,
    utc_now,
)
from docker_agent.persistence.telemetry import safe_error_message

EvaluationRunStatus = Literal["running", "succeeded", "failed"]
EvaluationCaseStatus = Literal["passed", "failed", "error"]

_SECRET_FRAGMENTS = (
    "api_key",
    "apikey",
    "base_url",
    "database_url",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "private_key",
    "credential",
)


@dataclass(frozen=True, slots=True)
class EvaluationRunRecord:
    id: str
    suite: str
    dataset_name: str
    dataset_version: str
    git_revision: str | None
    status: EvaluationRunStatus
    config_snapshot: dict[str, object]
    aggregate_metrics: dict[str, object]
    case_count: int
    passed_count: int
    failed_count: int
    error_type: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class EvaluationCaseRecord:
    id: str
    evaluation_run_id: str
    case_key: str
    case_id: str
    phase: str | None
    repeat: int | None
    status: EvaluationCaseStatus
    metrics: dict[str, object]
    details: dict[str, object]
    created_at: datetime


class EvaluationRunNotFound(KeyError):
    """Raised when an evaluation run does not exist."""


class EvaluationRunStateError(ValueError):
    """Raised when an invalid evaluation lifecycle transition is requested."""


class EvaluationCaseAlreadyExists(ValueError):
    """Raised when one run receives the same case_key twice."""


def dataset_version(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def resolve_git_revision(root: Path | None = None) -> str | None:
    base = (root or Path.cwd()).resolve()
    git_dir = _find_git_directory(base)
    if git_dir is None:
        return None

    head_path = git_dir / "HEAD"
    try:
        head = head_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    if not head.startswith("ref:"):
        return head or None

    ref_name = head.removeprefix("ref:").strip()
    ref_path = git_dir / ref_name
    try:
        revision = ref_path.read_text(encoding="utf-8").strip()
    except OSError:
        revision = _packed_ref_revision(git_dir, ref_name)

    return revision or None


def _find_git_directory(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        git_path = candidate / ".git"
        if git_path.is_dir():
            return git_path
    return None


def _packed_ref_revision(git_dir: Path, ref_name: str) -> str | None:
    packed_refs = git_dir / "packed-refs"
    try:
        lines = packed_refs.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    for line in lines:
        if not line or line.startswith(("#", "^")):
            continue
        revision, _, name = line.partition(" ")
        if name == ref_name:
            return revision.strip() or None
    return None


def sanitize_evaluation_payload(value: object) -> object:
    if isinstance(value, dict):
        sanitized: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            normalized = key.lower().replace("-", "_")
            if any(fragment in normalized for fragment in _SECRET_FRAGMENTS):
                sanitized[key] = {
                    "configured": bool(raw_value),
                    "redacted": True,
                }
            else:
                sanitized[key] = sanitize_evaluation_payload(raw_value)
        return sanitized
    if isinstance(value, list):
        return [sanitize_evaluation_payload(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_evaluation_payload(item) for item in value]
    if isinstance(value, str):
        return redact_log_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def create_evaluation_run(
    engine: Engine,
    *,
    suite: str,
    dataset_name: str,
    dataset_version_value: str,
    config_snapshot: dict[str, object] | None = None,
    git_revision: str | None = None,
    run_id: str | None = None,
) -> EvaluationRunRecord:
    normalized_suite = suite.strip()
    normalized_dataset_name = dataset_name.strip()
    normalized_dataset_version = dataset_version_value.strip()

    if not normalized_suite:
        raise ValueError("suite must not be empty")
    if not normalized_dataset_name:
        raise ValueError("dataset_name must not be empty")
    if not normalized_dataset_version:
        raise ValueError("dataset_version must not be empty")

    sanitized = sanitize_evaluation_payload(config_snapshot or {})
    if not isinstance(sanitized, dict):
        raise TypeError("config_snapshot must sanitize to an object")

    row = EvaluationRun(
        id=run_id or uuid4().hex,
        suite=normalized_suite,
        dataset_name=normalized_dataset_name,
        dataset_version=normalized_dataset_version,
        git_revision=git_revision.strip() if git_revision else None,
        status="running",
        config_snapshot=sanitized,
        aggregate_metrics={},
        case_count=0,
        passed_count=0,
        failed_count=0,
    )

    with Session(engine) as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        return _run_record(row)


def add_evaluation_case(
    engine: Engine,
    *,
    evaluation_run_id: str,
    case_key: str,
    case_id: str,
    status: EvaluationCaseStatus,
    metrics: dict[str, object] | None = None,
    details: dict[str, object] | None = None,
    phase: str | None = None,
    repeat: int | None = None,
) -> EvaluationCaseRecord:
    if status not in {"passed", "failed", "error"}:
        raise ValueError(f"unsupported evaluation case status: {status}")

    normalized_run_id = evaluation_run_id.strip()
    normalized_case_key = case_key.strip()
    normalized_case_id = case_id.strip()
    if not normalized_run_id:
        raise ValueError("evaluation_run_id must not be empty")
    if not normalized_case_key:
        raise ValueError("case_key must not be empty")
    if not normalized_case_id:
        raise ValueError("case_id must not be empty")
    if repeat is not None and repeat <= 0:
        raise ValueError("repeat must be positive")

    sanitized_metrics = sanitize_evaluation_payload(metrics or {})
    sanitized_details = sanitize_evaluation_payload(details or {})
    if not isinstance(sanitized_metrics, dict):
        raise TypeError("metrics must sanitize to an object")
    if not isinstance(sanitized_details, dict):
        raise TypeError("details must sanitize to an object")

    with Session(engine) as session:
        if session.get(EvaluationRun, normalized_run_id) is None:
            raise EvaluationRunNotFound(normalized_run_id)

        row = EvaluationCaseResult(
            id=uuid4().hex,
            evaluation_run_id=normalized_run_id,
            case_key=normalized_case_key,
            case_id=normalized_case_id,
            phase=phase.strip() if phase else None,
            repeat=repeat,
            status=status,
            metrics=sanitized_metrics,
            details=sanitized_details,
        )
        session.add(row)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise EvaluationCaseAlreadyExists(normalized_case_key) from exc
        session.refresh(row)
        return _case_record(row)


def finalize_evaluation_run_success(
    engine: Engine,
    run_id: str,
    *,
    aggregate_metrics: dict[str, object],
) -> EvaluationRunRecord:
    return _finalize_evaluation_run(
        engine,
        run_id,
        status="succeeded",
        aggregate_metrics=aggregate_metrics,
        error=None,
    )


def finalize_evaluation_run_failure(
    engine: Engine,
    run_id: str,
    *,
    error: BaseException,
    aggregate_metrics: dict[str, object] | None = None,
) -> EvaluationRunRecord:
    return _finalize_evaluation_run(
        engine,
        run_id,
        status="failed",
        aggregate_metrics=aggregate_metrics or {},
        error=error,
    )


def get_evaluation_run(
    engine: Engine,
    run_id: str,
) -> EvaluationRunRecord:
    normalized = run_id.strip()
    if not normalized:
        raise ValueError("run_id must not be empty")

    with Session(engine) as session:
        row = session.get(EvaluationRun, normalized)
        if row is None:
            raise EvaluationRunNotFound(normalized)
        return _run_record(row)


def list_evaluation_runs(
    engine: Engine,
    *,
    suite: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[EvaluationRunRecord, ...]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    if offset < 0:
        raise ValueError("offset must not be negative")

    statement = select(EvaluationRun)
    if suite is not None:
        normalized_suite = suite.strip()
        if not normalized_suite:
            raise ValueError("suite must not be empty")
        statement = statement.where(EvaluationRun.suite == normalized_suite)

    statement = (
        statement.order_by(EvaluationRun.started_at.desc(), EvaluationRun.id)
        .offset(offset)
        .limit(limit)
    )
    with Session(engine) as session:
        return tuple(_run_record(row) for row in session.scalars(statement))


def list_evaluation_cases(
    engine: Engine,
    run_id: str,
) -> tuple[EvaluationCaseRecord, ...]:
    normalized = run_id.strip()
    if not normalized:
        raise ValueError("run_id must not be empty")

    with Session(engine) as session:
        if session.get(EvaluationRun, normalized) is None:
            raise EvaluationRunNotFound(normalized)
        rows = session.scalars(
            select(EvaluationCaseResult)
            .where(EvaluationCaseResult.evaluation_run_id == normalized)
            .order_by(
                EvaluationCaseResult.created_at,
                EvaluationCaseResult.id,
            )
        ).all()
        return tuple(_case_record(row) for row in rows)


def _finalize_evaluation_run(
    engine: Engine,
    run_id: str,
    *,
    status: Literal["succeeded", "failed"],
    aggregate_metrics: dict[str, object],
    error: BaseException | None,
) -> EvaluationRunRecord:
    normalized = run_id.strip()
    if not normalized:
        raise ValueError("run_id must not be empty")

    sanitized_metrics = sanitize_evaluation_payload(aggregate_metrics)
    if not isinstance(sanitized_metrics, dict):
        raise TypeError("aggregate_metrics must sanitize to an object")

    with Session(engine) as session:
        row = session.get(EvaluationRun, normalized)
        if row is None:
            raise EvaluationRunNotFound(normalized)
        if row.status != "running":
            raise EvaluationRunStateError(
                f"evaluation run {normalized!r} is already finalized"
            )

        statuses = session.scalars(
            select(EvaluationCaseResult.status).where(
                EvaluationCaseResult.evaluation_run_id == normalized
            )
        ).all()
        row.status = status
        row.aggregate_metrics = sanitized_metrics
        row.case_count = len(statuses)
        row.passed_count = sum(item == "passed" for item in statuses)
        row.failed_count = sum(item != "passed" for item in statuses)
        row.error_type = type(error).__name__ if error is not None else None
        row.error_message = (
            safe_error_message(error) if error is not None else None
        )
        row.completed_at = utc_now()

        session.commit()
        session.refresh(row)
        return _run_record(row)


def _run_record(row: EvaluationRun) -> EvaluationRunRecord:
    status = row.status
    if status not in {"running", "succeeded", "failed"}:
        raise ValueError(f"invalid stored evaluation run status: {status}")
    return EvaluationRunRecord(
        id=row.id,
        suite=row.suite,
        dataset_name=row.dataset_name,
        dataset_version=row.dataset_version,
        git_revision=row.git_revision,
        status=status,
        config_snapshot=dict(row.config_snapshot),
        aggregate_metrics=dict(row.aggregate_metrics),
        case_count=row.case_count,
        passed_count=row.passed_count,
        failed_count=row.failed_count,
        error_type=row.error_type,
        error_message=row.error_message,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


def _case_record(row: EvaluationCaseResult) -> EvaluationCaseRecord:
    status = row.status
    if status not in {"passed", "failed", "error"}:
        raise ValueError(f"invalid stored evaluation case status: {status}")
    return EvaluationCaseRecord(
        id=row.id,
        evaluation_run_id=row.evaluation_run_id,
        case_key=row.case_key,
        case_id=row.case_id,
        phase=row.phase,
        repeat=row.repeat,
        status=status,
        metrics=dict(row.metrics),
        details=dict(row.details),
        created_at=row.created_at,
    )
