from __future__ import annotations

import argparse
import json
from pathlib import Path

from docker_agent.docs.audit import audit_chunks


DEFAULT_INPUT = Path("data/processed/chunks.jsonl")


def load_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise TypeError(f"Expected a JSON object at {path}:{line_number}")
            rows.append(row)
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit processed Docker Docs chunks before embedding them."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--min-words", type=int, default=20)
    parser.add_argument("--max-words", type=int, default=600)
    parser.add_argument("--examples", type=int, default=10)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.input.exists():
        raise SystemExit(
            f"Chunk file not found: {args.input}. Run scripts/build_docs.py first."
        )

    rows = load_jsonl(args.input)
    report = audit_chunks(
        rows,
        min_words=args.min_words,
        max_words=args.max_words,
        max_examples=args.examples,
    )

    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
