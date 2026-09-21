from __future__ import annotations

import argparse
import json
from dataclasses import asdict

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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    engine = create_db_engine(register_pgvector_types=False)

    try:
        comparison = compare_evaluation_runs(
            engine,
            baseline_run_id=args.baseline,
            candidate_run_id=args.candidate,
            max_regression=args.max_regression,
        )
    except EvaluationRunNotFound as exc:
        print(
            json.dumps(
                {
                    "error": "evaluation_run_not_found",
                    "run_id": str(exc.args[0]) if exc.args else None,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    except (EvaluationComparisonError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "error": "comparison_invalid",
                    "detail": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    print(
        json.dumps(
            asdict(comparison),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if comparison.gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
