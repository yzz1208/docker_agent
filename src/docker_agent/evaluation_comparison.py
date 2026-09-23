from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.engine import Engine

from docker_agent.persistence.evaluation import (
    EvaluationCaseRecord,
    EvaluationRunRecord,
    get_evaluation_run,
    list_evaluation_cases,
)

MetricDirection = Literal["higher_is_better", "lower_is_better"]
ComparisonVerdict = Literal["pass", "regression", "incomplete"]

_QUALITY_METRIC_HINTS = (
    "accuracy",
    "coverage",
    "duration",
    "f1",
    "latency",
    "match",
    "precision",
    "rate",
    "recall",
    "score",
)
_QUALITY_METRIC_SUFFIXES = (
    "_call_count",
    "_calls_per_case",
)
_LOWER_IS_BETTER_HINTS = (
    "call_count",
    "calls_per_case",
    "duration",
    "error_rate",
    "failure_rate",
    "latency",
)


@dataclass(frozen=True, slots=True)
class MetricComparison:
    path: str
    baseline_value: float
    candidate_value: float
    delta: float
    quality_delta: float
    direction: MetricDirection
    threshold: float
    regression: bool
    improvement: bool


@dataclass(frozen=True, slots=True)
class BehaviorChange:
    case_key: str
    field: str
    baseline_value: object
    candidate_value: object


@dataclass(frozen=True, slots=True)
class ConfigurationChange:
    path: str
    baseline_value: object
    candidate_value: object


@dataclass(frozen=True, slots=True)
class EvaluationComparison:
    baseline_run_id: str
    candidate_run_id: str
    agent_type: str | None
    suite: str
    dataset_name: str
    dataset_version: str
    max_regression: float
    verdict: ComparisonVerdict
    gate_passed: bool
    common_case_count: int
    baseline_only_case_keys: tuple[str, ...]
    candidate_only_case_keys: tuple[str, ...]
    new_failures: tuple[str, ...]
    new_passes: tuple[str, ...]
    unchanged_failures: tuple[str, ...]
    metric_comparisons: tuple[MetricComparison, ...]
    behavior_changes: tuple[BehaviorChange, ...]
    configuration_changes: tuple[ConfigurationChange, ...]


class EvaluationComparisonError(ValueError):
    """Raised when two evaluation runs cannot be meaningfully compared."""


def compare_evaluation_runs(
    engine: Engine,
    *,
    baseline_run_id: str,
    candidate_run_id: str,
    max_regression: float = 0.02,
) -> EvaluationComparison:
    if max_regression < 0:
        raise ValueError("max_regression must not be negative")

    baseline = get_evaluation_run(engine, baseline_run_id)
    candidate = get_evaluation_run(engine, candidate_run_id)
    _validate_comparable_runs(baseline, candidate)

    baseline_cases = {
        case.case_key: case
        for case in list_evaluation_cases(engine, baseline.id)
    }
    candidate_cases = {
        case.case_key: case
        for case in list_evaluation_cases(engine, candidate.id)
    }

    baseline_keys = set(baseline_cases)
    candidate_keys = set(candidate_cases)
    common_keys = sorted(baseline_keys & candidate_keys)
    baseline_only = tuple(sorted(baseline_keys - candidate_keys))
    candidate_only = tuple(sorted(candidate_keys - baseline_keys))

    new_failures: list[str] = []
    new_passes: list[str] = []
    unchanged_failures: list[str] = []
    behavior_changes: list[BehaviorChange] = []

    for case_key in common_keys:
        baseline_case = baseline_cases[case_key]
        candidate_case = candidate_cases[case_key]

        if (
            baseline_case.status == "passed"
            and candidate_case.status != "passed"
        ):
            new_failures.append(case_key)
        elif (
            baseline_case.status != "passed"
            and candidate_case.status == "passed"
        ):
            new_passes.append(case_key)
        elif (
            baseline_case.status != "passed"
            and candidate_case.status != "passed"
        ):
            unchanged_failures.append(case_key)

        behavior_changes.extend(
            _compare_case_behavior(
                baseline_case,
                candidate_case,
            )
        )

    metric_comparisons = _compare_aggregate_metrics(
        baseline.aggregate_metrics,
        candidate.aggregate_metrics,
        threshold=max_regression,
    )
    configuration_changes = _compare_configuration(
        baseline.config_snapshot,
        candidate.config_snapshot,
    )

    incomplete = bool(baseline_only or candidate_only)
    regression = bool(new_failures) or any(
        metric.regression for metric in metric_comparisons
    )

    if incomplete:
        verdict: ComparisonVerdict = "incomplete"
    elif regression:
        verdict = "regression"
    else:
        verdict = "pass"

    return EvaluationComparison(
        baseline_run_id=baseline.id,
        candidate_run_id=candidate.id,
        agent_type=baseline.agent_type,
        suite=baseline.suite,
        dataset_name=baseline.dataset_name,
        dataset_version=baseline.dataset_version,
        max_regression=max_regression,
        verdict=verdict,
        gate_passed=not incomplete and not regression,
        common_case_count=len(common_keys),
        baseline_only_case_keys=baseline_only,
        candidate_only_case_keys=candidate_only,
        new_failures=tuple(new_failures),
        new_passes=tuple(new_passes),
        unchanged_failures=tuple(unchanged_failures),
        metric_comparisons=metric_comparisons,
        behavior_changes=tuple(behavior_changes),
        configuration_changes=configuration_changes,
    )


def _validate_comparable_runs(
    baseline: EvaluationRunRecord,
    candidate: EvaluationRunRecord,
) -> None:
    if baseline.id == candidate.id:
        raise EvaluationComparisonError(
            "baseline and candidate evaluation runs must be different"
        )
    if baseline.status != "succeeded" or candidate.status != "succeeded":
        raise EvaluationComparisonError(
            "baseline and candidate evaluation runs must both be succeeded"
        )
    if baseline.agent_type != candidate.agent_type:
        raise EvaluationComparisonError(
            "baseline and candidate Agent types must match"
        )
    if baseline.suite != candidate.suite:
        raise EvaluationComparisonError(
            "baseline and candidate suites must match"
        )
    if baseline.dataset_version != candidate.dataset_version:
        raise EvaluationComparisonError(
            "baseline and candidate dataset versions must match"
        )


def _compare_aggregate_metrics(
    baseline: dict[str, object],
    candidate: dict[str, object],
    *,
    threshold: float,
) -> tuple[MetricComparison, ...]:
    baseline_metrics = _numeric_quality_metrics(baseline)
    candidate_metrics = _numeric_quality_metrics(candidate)
    comparisons: list[MetricComparison] = []

    for path in sorted(set(baseline_metrics) & set(candidate_metrics)):
        baseline_value = baseline_metrics[path]
        candidate_value = candidate_metrics[path]
        delta = candidate_value - baseline_value
        direction = _metric_direction(path)
        quality_delta = (
            -delta
            if direction == "lower_is_better"
            else delta
        )
        comparisons.append(
            MetricComparison(
                path=path,
                baseline_value=baseline_value,
                candidate_value=candidate_value,
                delta=delta,
                quality_delta=quality_delta,
                direction=direction,
                threshold=threshold,
                regression=quality_delta < -threshold,
                improvement=quality_delta > threshold,
            )
        )

    return tuple(comparisons)


def _numeric_quality_metrics(
    value: dict[str, object],
) -> dict[str, float]:
    flattened: dict[str, float] = {}
    _collect_numeric_quality_metrics(value, "", flattened)
    return flattened


def _collect_numeric_quality_metrics(
    value: object,
    path: str,
    output: dict[str, float],
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            _collect_numeric_quality_metrics(
                child,
                child_path,
                output,
            )
        return

    if (
        path
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
    ):
        numeric = float(value)
        if (
            math.isfinite(numeric)
            and _is_quality_metric(path)
        ):
            output[path] = numeric


def _is_quality_metric(path: str) -> bool:
    normalized = path.lower()
    return (
        any(hint in normalized for hint in _QUALITY_METRIC_HINTS)
        or normalized.endswith(_QUALITY_METRIC_SUFFIXES)
    )


def _metric_direction(path: str) -> MetricDirection:
    normalized = path.lower()
    if any(hint in normalized for hint in _LOWER_IS_BETTER_HINTS):
        return "lower_is_better"
    return "higher_is_better"


def _compare_case_behavior(
    baseline: EvaluationCaseRecord,
    candidate: EvaluationCaseRecord,
) -> list[BehaviorChange]:
    baseline_behavior = _behavior_values(baseline)
    candidate_behavior = _behavior_values(candidate)
    changes: list[BehaviorChange] = []

    for field in sorted(set(baseline_behavior) | set(candidate_behavior)):
        baseline_value = baseline_behavior.get(field)
        candidate_value = candidate_behavior.get(field)
        if baseline_value != candidate_value:
            changes.append(
                BehaviorChange(
                    case_key=baseline.case_key,
                    field=field,
                    baseline_value=baseline_value,
                    candidate_value=candidate_value,
                )
            )

    return changes


def _behavior_values(
    case: EvaluationCaseRecord,
) -> dict[str, object]:
    actual = case.details.get("actual")
    if not isinstance(actual, dict):
        return {}

    values: dict[str, object] = {}
    for field in (
        "action",
        "capability",
        "contributing_agents",
        "current_agent_type",
        "needs_clarification",
        "route",
        "synthesized",
        "target_agent_type",
    ):
        if field in actual:
            values[field] = actual[field]
    if "tools" in actual:
        values["tools"] = actual["tools"]
    if "tools_called" in actual:
        values["tools"] = actual["tools_called"]
    if "container" in actual:
        values["container"] = actual["container"]
    return values


def _compare_configuration(
    baseline: dict[str, object],
    candidate: dict[str, object],
) -> tuple[ConfigurationChange, ...]:
    baseline_values = _flatten_values(baseline)
    candidate_values = _flatten_values(candidate)
    changes: list[ConfigurationChange] = []

    for path in sorted(set(baseline_values) | set(candidate_values)):
        baseline_value = baseline_values.get(path)
        candidate_value = candidate_values.get(path)
        if baseline_value != candidate_value:
            changes.append(
                ConfigurationChange(
                    path=path,
                    baseline_value=baseline_value,
                    candidate_value=candidate_value,
                )
            )

    return tuple(changes)


def _flatten_values(
    value: dict[str, object],
) -> dict[str, object]:
    output: dict[str, object] = {}
    _collect_values(value, "", output)
    return output


def _collect_values(
    value: object,
    path: str,
    output: dict[str, object],
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            _collect_values(child, child_path, output)
        return

    if isinstance(value, list):
        output[path] = value
        return

    if path:
        output[path] = value
