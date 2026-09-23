from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

from docker_agent.agent.registry import build_agent_registry
from docker_agent.config import get_settings
from docker_agent.db import create_db_engine, require_database_ready
from docker_agent.orchestration import (
    AgentHandoff,
    DelegationContext,
    OrchestratedSynthesisService,
    OrchestrationDecisionError,
    OrchestrationDecisionExpectation,
    OrchestrationDecisionModel,
    OrchestrationSynthesisError,
    OrchestrationSynthesisExpectation,
    SpecialistResultEnvelope,
    evaluate_orchestration_decision,
    evaluate_orchestration_synthesis,
    summarize_orchestration_by_category,
    summarize_orchestration_decisions,
    summarize_orchestration_synthesis,
)
from docker_agent.persistence import (
    add_evaluation_case,
    create_evaluation_run,
    dataset_version,
    finalize_evaluation_run_success,
    resolve_git_revision,
)
from docker_agent.rag.llm import OpenAICompatibleChatClient

DEFAULT_INPUT = Path("data/eval/orchestration_v1.jsonl")
DEFAULT_OUTPUT = Path("reports/orchestration_eval_latest.jsonl")


class CountingModel:
    def __init__(self, model: OpenAICompatibleChatClient) -> None:
        self.model = model
        self.calls = 0

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        self.calls += 1
        return self.model.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate platform orchestration decisions, safety guards, "
            "and public cross-Agent synthesis without executing specialists."
        )
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument(
        "--decision-latency-budget-ms",
        type=float,
        default=8_000.0,
    )
    parser.add_argument(
        "--synthesis-latency-budget-ms",
        type=float,
        default=12_000.0,
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Persist the run and per-case results to PostgreSQL.",
    )
    parser.add_argument("--summary-output", type=Path, default=None)
    return parser.parse_args()


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON at {path}:{line_number}: {exc}"
                ) from exc
            if not isinstance(row, dict):
                raise TypeError(
                    f"Expected an object at {path}:{line_number}"
                )

            case_id = str(row.get("id") or "").strip()
            kind = str(row.get("kind") or "").strip()
            category = str(row.get("category") or "").strip()
            if not case_id or not category:
                raise ValueError(
                    f"Case at {path}:{line_number} requires id/category"
                )
            if kind not in {"decision", "guard", "synthesis"}:
                raise ValueError(
                    f"Case {case_id} has unsupported kind {kind!r}"
                )
            if kind in {"decision", "guard"}:
                _decision_expectation(row)
            else:
                _synthesis_expectation(row)
                _specialist_results(row)
            cases.append(row)
    return cases


def _model(
    *,
    temperature: float,
    max_tokens: int,
) -> OpenAICompatibleChatClient:
    settings = get_settings()
    if not settings.model_name.strip() or not settings.model_base_url.strip():
        raise SystemExit(
            "MODEL_NAME and MODEL_BASE_URL must be configured in .env"
        )
    configured_tokens = settings.model_max_tokens
    token_limit = (
        min(configured_tokens, max_tokens)
        if configured_tokens is not None
        else max_tokens
    )
    return OpenAICompatibleChatClient(
        model=settings.model_name,
        base_url=settings.model_base_url,
        api_key=settings.model_api_key,
        timeout_seconds=settings.model_timeout_seconds,
        temperature=temperature,
        max_tokens=token_limit,
        max_retries=settings.model_max_retries,
        retry_backoff_seconds=settings.model_retry_backoff_seconds,
    )


def _context(row: dict[str, Any]) -> DelegationContext:
    original_query = str(
        row.get("original_query")
        or row.get("question")
        or "orchestration evaluation"
    ).strip()
    raw_handoffs = row.get("context_handoffs", [])
    if not isinstance(raw_handoffs, list):
        raise TypeError("context_handoffs must be a list")

    handoffs: list[AgentHandoff] = []
    for index, raw in enumerate(raw_handoffs, start=1):
        if not isinstance(raw, dict):
            raise TypeError("context handoff must be an object")
        source_raw = raw.get("source_agent_type")
        source = (
            str(source_raw).strip()
            if source_raw is not None
            else None
        )
        handoffs.append(
            AgentHandoff(
                index=index,
                source_agent_type=source or None,
                target_agent_type=str(
                    raw.get("target_agent_type") or ""
                ).strip(),
                capability=str(raw.get("capability") or "").strip(),
                reason=str(raw.get("reason") or "evaluation").strip(),
            )
        )

    return DelegationContext(
        original_query=original_query,
        handoffs=tuple(handoffs),
    )


def _decision_expectation(
    row: dict[str, Any],
) -> OrchestrationDecisionExpectation:
    raw = row.get("expected")
    if not isinstance(raw, dict):
        raise TypeError("decision case expected must be an object")
    return OrchestrationDecisionExpectation(
        action=_optional_string(raw.get("action")),
        target_agent_type=_optional_string(
            raw.get("target_agent_type")
        ),
        capability=_optional_string(raw.get("capability")),
        clarification_required=(
            raw.get("clarification_required") is True
        ),
        blocked=raw.get("blocked") is True,
    )


def _synthesis_expectation(
    row: dict[str, Any],
) -> OrchestrationSynthesisExpectation:
    raw = row.get("expected")
    if not isinstance(raw, dict):
        raise TypeError("synthesis case expected must be an object")
    agents_raw = raw.get("contributing_agents")
    if not isinstance(agents_raw, list):
        raise TypeError("contributing_agents must be a list")
    return OrchestrationSynthesisExpectation(
        contributing_agents=tuple(
            str(item).strip() for item in agents_raw
        ),
        answer_required=raw.get("answer_required") is True,
        clarification_required=(
            raw.get("clarification_required") is True
        ),
        unresolved_uncertainty_required=(
            raw.get("unresolved_uncertainty_required") is True
        ),
    )


def _specialist_results(
    row: dict[str, Any],
) -> tuple[SpecialistResultEnvelope, ...]:
    raw_results = row.get("specialist_results")
    if not isinstance(raw_results, list) or not raw_results:
        raise ValueError(
            "synthesis case requires specialist_results"
        )

    results: list[SpecialistResultEnvelope] = []
    for raw in raw_results:
        if not isinstance(raw, dict):
            raise TypeError("specialist result must be an object")
        clarification = _optional_string(raw.get("clarification"))
        results.append(
            SpecialistResultEnvelope(
                agent_type=str(raw.get("agent_type") or "").strip(),
                route=str(raw.get("route") or "").strip(),
                reason=str(raw.get("reason") or "").strip(),
                needs_clarification=(
                    raw.get("needs_clarification") is True
                ),
                clarification=clarification,
                summary=_optional_string(raw.get("summary")),
            )
        )
    return tuple(results)


def _run_decision_case(
    row: dict[str, Any],
    *,
    model: OrchestrationDecisionModel,
    counting_model: CountingModel,
    latency_budget_ms: float,
) -> tuple[object, dict[str, Any], bool]:
    case_id = str(row["id"])
    category = str(row["category"])
    expected = _decision_expectation(row)
    context = _context(row)
    source = _optional_string(row.get("source_agent_type"))
    kind = str(row["kind"])
    decision = None
    blocked = False
    error: str | None = None

    before_calls = counting_model.calls
    started = perf_counter()
    try:
        if kind == "guard":
            raw_candidate = row.get("candidate_decision")
            if not isinstance(raw_candidate, dict):
                raise TypeError(
                    "guard case requires candidate_decision object"
                )
            decision = model.validate(
                json.dumps(raw_candidate, ensure_ascii=False),
                context=context,
                source_agent_type=source,
            )
        else:
            question = str(row.get("question") or "").strip()
            if not question:
                raise ValueError(
                    f"decision case {case_id} requires question"
                )
            decision = model.decide(
                question,
                context=context,
                source_agent_type=source,
            )
    except OrchestrationDecisionError as exc:
        blocked = True
        error = str(exc)
    elapsed_ms = (perf_counter() - started) * 1000
    call_count = counting_model.calls - before_calls

    metrics = evaluate_orchestration_decision(
        case_id=case_id,
        category=category,
        expected=expected,
        decision=decision,
        blocked=blocked,
    )
    latency_budget_match = (
        True
        if kind == "guard"
        else elapsed_ms <= latency_budget_ms
    )
    actual = (
        {
            "action": decision.action,
            "target_agent_type": decision.target_agent_type,
            "capability": decision.capability,
            "clarification_present": bool(decision.clarification),
        }
        if decision is not None
        else {
            "blocked": blocked,
        }
    )
    row_out: dict[str, Any] = {
        "id": case_id,
        "kind": kind,
        "category": category,
        "expected": asdict(expected),
        "actual": actual,
        "metrics": {
            **asdict(metrics),
            "specialist_selection_match": (
                metrics.specialist_selection_match
            ),
            "exact_match": metrics.exact_match,
            "latency_budget_match": latency_budget_match,
        },
        "performance": {
            "latency_ms": round(elapsed_ms, 3),
            "model_call_count": call_count,
        },
    }
    if error is not None:
        row_out["validation_error"] = error
    passed = metrics.exact_match and latency_budget_match
    return metrics, row_out, passed


def _run_synthesis_case(
    row: dict[str, Any],
    *,
    service: OrchestratedSynthesisService,
    counting_model: CountingModel,
    latency_budget_ms: float,
) -> tuple[object, dict[str, Any], bool]:
    case_id = str(row["id"])
    category = str(row["category"])
    expected = _synthesis_expectation(row)
    results = _specialist_results(row)
    observations_raw = row.get("user_observations", [])
    if not isinstance(observations_raw, list):
        raise TypeError("user_observations must be a list")
    observations = tuple(
        str(item).strip() for item in observations_raw
        if str(item).strip()
    )
    original_query = str(
        row.get("original_query") or ""
    ).strip()
    if not original_query:
        raise ValueError(
            f"synthesis case {case_id} requires original_query"
        )

    before_calls = counting_model.calls
    started = perf_counter()
    result = None
    error: str | None = None
    try:
        result = service.synthesize(
            original_query=original_query,
            user_observations=observations,
            specialist_results=results,
        )
    except OrchestrationSynthesisError as exc:
        error = str(exc)
    elapsed_ms = (perf_counter() - started) * 1000
    call_count = counting_model.calls - before_calls

    metrics = evaluate_orchestration_synthesis(
        case_id=case_id,
        category=category,
        expected=expected,
        result=result,
    )
    latency_budget_match = elapsed_ms <= latency_budget_ms
    actual = (
        {
            "contributing_agents": list(
                result.contributing_agents
            ),
            "needs_clarification": result.needs_clarification,
            "answer_present": bool(result.answer),
            "uncertainty_count": len(
                result.unresolved_uncertainties
            ),
        }
        if result is not None
        else {}
    )
    row_out: dict[str, Any] = {
        "id": case_id,
        "kind": "synthesis",
        "category": category,
        "expected": asdict(expected),
        "actual": actual,
        "metrics": {
            **asdict(metrics),
            "exact_match": metrics.exact_match,
            "latency_budget_match": latency_budget_match,
        },
        "performance": {
            "latency_ms": round(elapsed_ms, 3),
            "model_call_count": call_count,
        },
    }
    if error is not None:
        row_out["validation_error"] = error
    passed = metrics.exact_match and latency_budget_match
    return metrics, row_out, passed


def _performance_summary(
    rows: list[dict[str, Any]],
) -> dict[str, float | int]:
    latencies = [
        float(row["performance"]["latency_ms"])
        for row in rows
    ]
    call_counts = [
        int(row["performance"]["model_call_count"])
        for row in rows
    ]
    budget_matches = [
        row["metrics"].get("latency_budget_match") is True
        for row in rows
    ]
    if not rows:
        return {
            "attempts": 0,
            "latency_ms_average": 0.0,
            "latency_ms_p95": 0.0,
            "model_call_count": 0,
            "average_model_calls_per_case": 0.0,
            "latency_budget_pass_rate": 0.0,
        }
    ordered = sorted(latencies)
    p95_index = max(
        0,
        min(len(ordered) - 1, int(0.95 * len(ordered) + 0.999) - 1),
    )
    return {
        "attempts": len(rows),
        "latency_ms_average": round(mean(latencies), 3),
        "latency_ms_p95": round(ordered[p95_index], 3),
        "model_call_count": sum(call_counts),
        "average_model_calls_per_case": round(
            mean(call_counts),
            4,
        ),
        "latency_budget_pass_rate": mean(
            1.0 if item else 0.0
            for item in budget_matches
        ),
    }


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def main() -> None:
    args = parse_args()
    if not args.input.exists():
        raise SystemExit(
            f"Orchestration evaluation file not found: {args.input}"
        )
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be positive")
    if args.repeats <= 0:
        raise SystemExit("--repeats must be positive")
    if args.decision_latency_budget_ms <= 0:
        raise SystemExit(
            "--decision-latency-budget-ms must be positive"
        )
    if args.synthesis_latency_budget_ms <= 0:
        raise SystemExit(
            "--synthesis-latency-budget-ms must be positive"
        )

    cases = load_cases(args.input)
    if args.limit is not None:
        cases = cases[: args.limit]
    if not cases:
        raise SystemExit(
            "Orchestration evaluation file contains no cases"
        )

    registry = build_agent_registry()
    decision_counting = CountingModel(
        _model(temperature=0.0, max_tokens=320)
    )
    synthesis_counting = CountingModel(
        _model(temperature=0.1, max_tokens=1200)
    )
    decision_model = OrchestrationDecisionModel(
        registry=registry,
        model=decision_counting,
        max_hops=2,
    )
    synthesis_service = OrchestratedSynthesisService(
        model=synthesis_counting,
    )

    decision_metrics: list[Any] = []
    synthesis_metrics: list[Any] = []
    rows: list[dict[str, Any]] = []

    for case in cases:
        for repeat in range(1, args.repeats + 1):
            if case["kind"] == "synthesis":
                metrics, row, passed = _run_synthesis_case(
                    case,
                    service=synthesis_service,
                    counting_model=synthesis_counting,
                    latency_budget_ms=args.synthesis_latency_budget_ms,
                )
                synthesis_metrics.append(metrics)
            else:
                metrics, row, passed = _run_decision_case(
                    case,
                    model=decision_model,
                    counting_model=decision_counting,
                    latency_budget_ms=args.decision_latency_budget_ms,
                )
                decision_metrics.append(metrics)
            row["repeat"] = repeat
            rows.append(row)
            print(
                f"[{row['id']}] {row['kind']} "
                f"exact={row['metrics']['exact_match']} "
                f"latency_budget={row['metrics']['latency_budget_match']} "
                f"calls={row['performance']['model_call_count']} "
                f"status={'pass' if passed else 'fail'}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                json.dumps(row, ensure_ascii=False) + "\n"
            )

    passed_count = sum(
        row["metrics"]["exact_match"] is True
        and row["metrics"]["latency_budget_match"] is True
        for row in rows
    )
    summary: dict[str, Any] = {
        "cases": len(cases),
        "attempts": len(rows),
        "repeats": args.repeats,
        "passed_count": passed_count,
        "failed_count": len(rows) - passed_count,
        "overall_pass_rate": (
            passed_count / len(rows)
            if rows
            else 0.0
        ),
        "decision": summarize_orchestration_decisions(
            decision_metrics
        ),
        "synthesis": summarize_orchestration_synthesis(
            synthesis_metrics
        ),
        "by_category": summarize_orchestration_by_category(
            decision_metrics,
            synthesis_metrics,
        ),
        "performance": _performance_summary(rows),
        "output": str(args.output),
        "note": (
            "This suite evaluates orchestration decisions, guards, and "
            "public-result synthesis. It never executes specialist Agents "
            "or Docker tools."
        ),
    }

    if args.persist:
        settings = get_settings()
        engine = create_db_engine(register_pgvector_types=False)
        require_database_ready(engine)
        evaluation_run = create_evaluation_run(
            engine,
            suite="orchestration",
            agent_type="auto_orchestration",
            dataset_name=args.input.name,
            dataset_version_value=dataset_version(args.input),
            git_revision=resolve_git_revision(),
            config_snapshot={
                "model_name": settings.model_name,
                "model_base_url": settings.model_base_url,
                "model_api_key": settings.model_api_key,
                "decision_temperature": 0.0,
                "decision_max_tokens": 320,
                "synthesis_temperature": 0.1,
                "synthesis_max_tokens": 1200,
                "max_hops": 2,
                "repeats": args.repeats,
                "limit": args.limit,
                "decision_latency_budget_ms": (
                    args.decision_latency_budget_ms
                ),
                "synthesis_latency_budget_ms": (
                    args.synthesis_latency_budget_ms
                ),
            },
        )

        for row in rows:
            metrics_row = row["metrics"]
            case_passed = (
                metrics_row["exact_match"] is True
                and metrics_row["latency_budget_match"] is True
            )
            add_evaluation_case(
                engine,
                evaluation_run_id=evaluation_run.id,
                case_key=(
                    f"{row['id']}:{row['kind']}:{row['repeat']}"
                ),
                case_id=str(row["id"]),
                phase=str(row["kind"]),
                repeat=int(row["repeat"]),
                status="passed" if case_passed else "failed",
                metrics={
                    **metrics_row,
                    **row["performance"],
                },
                details={
                    key: value
                    for key, value in row.items()
                    if key not in {"metrics", "performance"}
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
        args.summary_output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        args.summary_output.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )

    print("\nSummary")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
