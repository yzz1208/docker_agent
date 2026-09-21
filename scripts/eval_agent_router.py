from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from docker_agent.agent.evaluation import (
    AgentEvalCase,
    AgentPlanExpectation,
    AgentPlanMetrics,
    evaluate_agent_plan,
    summarize_agent_metrics,
    summarize_by_phase,
)
from docker_agent.agent.router import AgentRoutingError, route_question
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

DEFAULT_INPUT = Path("data/eval/agent_router_v1.jsonl")
DEFAULT_OUTPUT = Path("reports/agent_router_eval_latest.jsonl")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate Docker Agent Router decisions without executing Docker tools."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="Repeat each route decision to check stability. No Docker tools are executed.",
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Persist this evaluation run and per-case results to PostgreSQL.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=None,
        help="Optionally write the aggregate summary JSON to this path.",
    )
    return parser.parse_args()


def load_cases(path: Path) -> list[AgentEvalCase]:
    cases: list[AgentEvalCase] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row: Any = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise TypeError(f"Expected a JSON object at {path}:{line_number}")

            case_id = str(row.get("id") or "").strip()
            question = str(row.get("question") or "").strip()
            expected = _parse_expectation(row.get("expected"), case_id or "<unknown>")

            follow_up_message: str | None = None
            follow_up_expected: AgentPlanExpectation | None = None
            follow_up = row.get("follow_up")
            if follow_up is not None:
                if not isinstance(follow_up, dict):
                    raise TypeError(f"Case {case_id} follow_up must be an object")
                follow_up_message = str(follow_up.get("message") or "").strip()
                if not follow_up_message:
                    raise ValueError(f"Case {case_id} follow_up requires message")
                follow_up_expected = _parse_expectation(
                    follow_up.get("expected"),
                    f"{case_id}.follow_up",
                )

            if not case_id or not question:
                raise ValueError(f"Case at {path}:{line_number} requires id and question")

            cases.append(
                AgentEvalCase(
                    case_id=case_id,
                    question=question,
                    expected=expected,
                    follow_up_message=follow_up_message,
                    follow_up_expected=follow_up_expected,
                )
            )
    return cases


def _parse_expectation(raw: Any, label: str) -> AgentPlanExpectation:
    if not isinstance(raw, dict):
        raise TypeError(f"{label} expected must be an object")

    route = str(raw.get("route") or "").strip()
    if route not in {"docs_only", "runtime_tools", "clarify"}:
        raise ValueError(f"{label} has unsupported expected route: {route!r}")

    tools_raw = raw.get("tools", [])
    if not isinstance(tools_raw, list):
        raise TypeError(f"{label} expected tools must be a list")

    container_raw = raw.get("container_ref")
    if container_raw is not None and not isinstance(container_raw, str):
        raise TypeError(f"{label} expected container_ref must be string or null")

    use_docs = raw.get("use_docs")
    if not isinstance(use_docs, bool):
        raise TypeError(f"{label} expected use_docs must be boolean")

    return AgentPlanExpectation(
        route=route,
        tools=frozenset(str(item) for item in tools_raw),
        container_ref=container_raw,
        use_docs=use_docs,
    )


def _router_model() -> OpenAICompatibleChatClient:
    settings = get_settings()
    if not settings.model_name.strip() or not settings.model_base_url.strip():
        raise SystemExit("MODEL_NAME and MODEL_BASE_URL must be configured in .env")

    return OpenAICompatibleChatClient(
        model=settings.model_name,
        base_url=settings.model_base_url,
        api_key=settings.model_api_key,
        timeout_seconds=settings.model_timeout_seconds,
        temperature=0.0,
    )


def _run_plan(
    *,
    case_id: str,
    phase: str,
    question: str,
    expected: AgentPlanExpectation,
    model: OpenAICompatibleChatClient,
) -> tuple[AgentPlanMetrics, dict[str, Any]]:
    error: str | None = None
    decision = None

    try:
        decision = route_question(question, model)
    except AgentRoutingError as exc:
        error = str(exc)

    metrics = evaluate_agent_plan(
        case_id=case_id,
        phase=phase,
        expected=expected,
        decision=decision,
    )

    row: dict[str, Any] = {
        "id": case_id,
        "phase": phase,
        "question": question,
        "expected": {
            "route": expected.route,
            "tools": sorted(expected.tools),
            "container_ref": expected.container_ref,
            "use_docs": expected.use_docs,
        },
        "metrics": {
            "valid": metrics.valid,
            "route_match": metrics.route_match,
            "tool_exact_match": metrics.tool_exact_match,
            "container_ref_match": metrics.container_ref_match,
            "use_docs_match": metrics.use_docs_match,
            "clarification_present_match": metrics.clarification_present_match,
            "exact_plan_match": metrics.exact_plan_match,
        },
    }

    if decision is not None:
        row["actual"] = {
            "route": decision.route,
            "reason": decision.reason,
            "tools": list(decision.tools),
            "container_ref": decision.container_ref,
            "use_docs": decision.use_docs,
            "clarification": decision.clarification,
        }
    if error is not None:
        row["validation_error"] = error

    return metrics, row



def _print_failure(row: dict[str, Any]) -> None:
    """Print a compact expected-vs-actual diff for one failed plan."""

    expected = row.get("expected", {})
    actual = row.get("actual")
    print("  expected:")
    print(f"    route={expected.get('route')}")
    print(f"    tools={expected.get('tools')}")
    print(f"    container_ref={expected.get('container_ref')}")
    print(f"    use_docs={expected.get('use_docs')}")

    if isinstance(actual, dict):
        print("  actual:")
        print(f"    route={actual.get('route')}")
        print(f"    tools={actual.get('tools')}")
        print(f"    container_ref={actual.get('container_ref')}")
        print(f"    use_docs={actual.get('use_docs')}")
        print(f"    reason={actual.get('reason')}")
    elif "validation_error" in row:
        print(f"  validation_error={row['validation_error']}")


def main() -> None:
    args = parse_args()
    if not args.input.exists():
        raise SystemExit(f"Agent evaluation file not found: {args.input}")
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be positive")
    if args.repeats <= 0:
        raise SystemExit("--repeats must be positive")

    cases = load_cases(args.input)
    if args.limit is not None:
        cases = cases[: args.limit]
    if not cases:
        raise SystemExit("Agent evaluation file contains no cases")

    model = _router_model()
    metrics: list[AgentPlanMetrics] = []
    rows: list[dict[str, Any]] = []

    for case in cases:
        for repeat in range(1, args.repeats + 1):
            first_metrics, first_row = _run_plan(
                case_id=case.case_id,
                phase="initial",
                question=case.question,
                expected=case.expected,
                model=model,
            )
            first_row["repeat"] = repeat
            metrics.append(first_metrics)
            rows.append(first_row)

            print(
                f"[{case.case_id}] initial valid={first_metrics.valid} "
                f"route={first_metrics.route_match} "
                f"tools={first_metrics.tool_exact_match} "
                f"plan={first_metrics.exact_plan_match}"
            )
            if not first_metrics.exact_plan_match:
                _print_failure(first_row)

            if case.follow_up_message is None or case.follow_up_expected is None:
                continue

            effective_question = (
                f"{case.question}\n"
                f"User clarification: {case.follow_up_message}"
            )
            follow_metrics, follow_row = _run_plan(
                case_id=case.case_id,
                phase="follow_up",
                question=effective_question,
                expected=case.follow_up_expected,
                model=model,
            )
            follow_row["repeat"] = repeat
            follow_row["follow_up_message"] = case.follow_up_message
            metrics.append(follow_metrics)
            rows.append(follow_row)

            print(
                f"[{case.case_id}] follow_up valid={follow_metrics.valid} "
                f"route={follow_metrics.route_match} "
                f"tools={follow_metrics.tool_exact_match} "
                f"plan={follow_metrics.exact_plan_match}"
            )
            if not follow_metrics.exact_plan_match:
                _print_failure(follow_row)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    initial_metrics = [item for item in metrics if item.phase == "initial"]
    follow_up_metrics = [item for item in metrics if item.phase == "follow_up"]

    summary: dict[str, Any] = {
        "cases": len(cases),
        "repeats": args.repeats,
        "overall": summarize_agent_metrics(metrics),
        "by_phase": summarize_by_phase(metrics),
        "initial": summarize_agent_metrics(initial_metrics),
        "follow_up": summarize_agent_metrics(follow_up_metrics),
        "validation_blocks": sum(1 for item in metrics if not item.valid),
        "output": str(args.output),
        "note": (
            "This evaluates routing only. It never executes Docker tools and therefore "
            "does not measure runtime answer quality."
        ),
    }

    if args.persist:
        settings = get_settings()
        engine = create_db_engine(register_pgvector_types=False)
        require_database_ready(engine)
        evaluation_run = create_evaluation_run(
            engine,
            suite="agent_router",
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
            exact_match = metrics_row.get("exact_plan_match") is True
            case_id = str(row.get("id") or "")
            phase = str(row.get("phase") or "")
            repeat = int(row.get("repeat") or 1)
            add_evaluation_case(
                engine,
                evaluation_run_id=evaluation_run.id,
                case_key=f"{case_id}:{phase}:{repeat}",
                case_id=case_id,
                phase=phase or None,
                repeat=repeat,
                status="passed" if exact_match else "failed",
                metrics=metrics_row,
                details={
                    key: value
                    for key, value in row.items()
                    if key not in {"metrics", "question"}
                },
            )

        evaluation_run = finalize_evaluation_run_success(
            engine,
            evaluation_run.id,
            aggregate_metrics=summary,
        )
        summary["evaluation_run_id"] = evaluation_run.id

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
