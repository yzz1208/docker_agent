from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docker_agent.agent.infrastructure import (
    InfrastructureRoutingError,
    route_infrastructure_question,
)
from docker_agent.agent.infrastructure_evaluation import (
    InfrastructureRouteMetrics,
    evaluate_infrastructure_route,
    summarize_infrastructure_metrics,
)
from docker_agent.config import get_settings
from docker_agent.db import create_db_engine, require_database_ready
from docker_agent.persistence import (
    add_evaluation_case,
    create_evaluation_run,
    dataset_version,
    finalize_evaluation_run_success,
    resolve_git_revision,
)
from docker_agent.rag.llm import OpenAICompatibleChatClient

DEFAULT_INPUT = Path("data/eval/infrastructure_router_v1.jsonl")
DEFAULT_OUTPUT = Path("reports/infrastructure_router_eval_latest.jsonl")


@dataclass(frozen=True, slots=True)
class InfrastructureEvalCase:
    case_id: str
    question: str
    expected_route: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate Infrastructure Troubleshooter routing without "
            "live infrastructure access."
        )
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="Repeat each route decision to measure routing stability.",
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Persist the evaluation run and per-case results.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=None,
        help="Optionally write aggregate summary JSON to this path.",
    )
    return parser.parse_args()


def load_cases(path: Path) -> list[InfrastructureEvalCase]:
    cases: list[InfrastructureEvalCase] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row: Any = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON at {path}:{line_number}: {exc}"
                ) from exc
            if not isinstance(row, dict):
                raise TypeError(
                    f"Expected a JSON object at {path}:{line_number}"
                )

            case_id = str(row.get("id") or "").strip()
            question = str(row.get("question") or "").strip()
            expected_route = str(
                row.get("expected_route") or ""
            ).strip()
            if not case_id or not question:
                raise ValueError(
                    f"Case at {path}:{line_number} requires id and question"
                )
            if expected_route not in {"triage", "clarify"}:
                raise ValueError(
                    f"Case {case_id} has unsupported expected route "
                    f"{expected_route!r}"
                )
            cases.append(
                InfrastructureEvalCase(
                    case_id=case_id,
                    question=question,
                    expected_route=expected_route,
                )
            )
    return cases


def _router_model() -> OpenAICompatibleChatClient:
    settings = get_settings()
    if not settings.model_name.strip() or not settings.model_base_url.strip():
        raise SystemExit(
            "MODEL_NAME and MODEL_BASE_URL must be configured in .env"
        )
    return OpenAICompatibleChatClient(
        model=settings.model_name,
        base_url=settings.model_base_url,
        api_key=settings.model_api_key,
        timeout_seconds=settings.model_timeout_seconds,
        temperature=0.0,
        max_tokens=settings.model_max_tokens,
        max_retries=settings.model_max_retries,
        retry_backoff_seconds=settings.model_retry_backoff_seconds,
    )


def _run_case(
    case: InfrastructureEvalCase,
    *,
    repeat: int,
    model: OpenAICompatibleChatClient,
) -> tuple[InfrastructureRouteMetrics, dict[str, Any]]:
    decision = None
    error: str | None = None
    try:
        decision = route_infrastructure_question(case.question, model)
    except InfrastructureRoutingError as exc:
        error = str(exc)

    metrics = evaluate_infrastructure_route(
        case_id=case.case_id,
        expected_route=case.expected_route,
        decision=decision,
    )
    row: dict[str, Any] = {
        "id": case.case_id,
        "repeat": repeat,
        "expected": {"route": case.expected_route},
        "actual": (
            {
                "route": decision.route,
                "clarification": decision.clarification,
            }
            if decision is not None
            else None
        ),
        "metrics": {
            "valid": metrics.valid,
            "route_match": metrics.route_match,
            "clarification_present_match": (
                metrics.clarification_present_match
            ),
            "exact_match": metrics.exact_match,
        },
    }
    if error is not None:
        row["validation_error"] = error
    return metrics, row


def main() -> None:
    args = parse_args()
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be a positive integer")
    if args.repeats <= 0:
        raise SystemExit("--repeats must be a positive integer")

    cases = load_cases(args.input)
    if args.limit is not None:
        cases = cases[: args.limit]

    model = _router_model()
    metrics: list[InfrastructureRouteMetrics] = []
    rows: list[dict[str, Any]] = []

    for case in cases:
        for repeat in range(1, args.repeats + 1):
            case_metrics, row = _run_case(
                case,
                repeat=repeat,
                model=model,
            )
            metrics.append(case_metrics)
            rows.append(row)
            print(
                f"[{case.case_id}] repeat={repeat} "
                f"valid={case_metrics.valid} "
                f"route={case_metrics.route_match} "
                f"exact={case_metrics.exact_match}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary: dict[str, Any] = {
        "cases": len(cases),
        "repeats": args.repeats,
        "overall": summarize_infrastructure_metrics(metrics),
        "validation_blocks": sum(
            1 for item in metrics if not item.valid
        ),
        "output": str(args.output),
        "note": (
            "This evaluates routing only and never accesses live "
            "infrastructure."
        ),
    }

    if args.persist:
        settings = get_settings()
        engine = create_db_engine(register_pgvector_types=False)
        require_database_ready(engine)
        evaluation_run = create_evaluation_run(
            engine,
            suite="infrastructure_router",
            agent_type="infrastructure_troubleshooter",
            dataset_name=args.input.name,
            dataset_version_value=dataset_version(args.input),
            git_revision=resolve_git_revision(),
            config_snapshot={
                "model_name": settings.model_name,
                "model_base_url": settings.model_base_url,
                "model_api_key": settings.model_api_key,
                "temperature": 0.0,
                "repeats": args.repeats,
                "limit": args.limit,
            },
        )

        for row in rows:
            metrics_row = row.get("metrics")
            if not isinstance(metrics_row, dict):
                metrics_row = {}
            case_id = str(row.get("id") or "")
            repeat = int(row.get("repeat") or 1)
            add_evaluation_case(
                engine,
                evaluation_run_id=evaluation_run.id,
                case_key=f"{case_id}:initial:{repeat}",
                case_id=case_id,
                phase="initial",
                repeat=repeat,
                status=(
                    "passed"
                    if metrics_row.get("exact_match") is True
                    else "failed"
                ),
                metrics=metrics_row,
                details={
                    key: value
                    for key, value in row.items()
                    if key != "metrics"
                },
            )

        evaluation_run = finalize_evaluation_run_success(
            engine,
            evaluation_run.id,
            aggregate_metrics=summary,
        )
        summary["evaluation_run_id"] = evaluation_run.id
        engine.dispose()

    if args.summary_output is not None:
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        args.summary_output.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print("\nSummary")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
