from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from docker_agent.db import create_db_engine
from docker_agent.evaluation_comparison import (
    EvaluationComparisonError,
    compare_evaluation_runs,
)
from docker_agent.persistence import EvaluationRunNotFound


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare two persisted evaluation runs and fail on regression."
        )
    )
    parser.add_argument(
        "--baseline",
        required=True,
        help="Baseline evaluation run id.",
    )
    parser.add_argument(
        "--candidate",
        required=True,
        help="Candidate evaluation run id.",
    )
    parser.add_argument(
        "--max-regression",
        type=float,
        default=0.02,
        help=(
            "Maximum tolerated absolute quality regression before the gate "
            "fails. Default: 0.02."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optionally write the comparison JSON to this path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    engine = create_db_engine(register_pgvector_types=False)

    try:
        try:
            comparison = compare_evaluation_runs(
                engine,
                baseline_run_id=args.baseline,
                candidate_run_id=args.candidate,
                max_regression=args.max_regression,
            )
        except EvaluationRunNotFound as exc:
            payload = {
                "error": "evaluation_run_not_found",
                "run_id": str(exc.args[0]) if exc.args else None,
            }
            _emit_payload(payload, args.output)
            return 2
        except (EvaluationComparisonError, ValueError) as exc:
            payload = {
                "error": "comparison_invalid",
                "detail": str(exc),
            }
            _emit_payload(payload, args.output)
            return 2

        payload = asdict(comparison)
        _emit_payload(payload, args.output)
        return 0 if comparison.gate_passed else 1
    finally:
        engine.dispose()


def _emit_payload(
    payload: dict[str, object],
    output: Path | None,
) -> None:
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
    )
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    raise SystemExit(main())
