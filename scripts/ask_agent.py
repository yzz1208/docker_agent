from __future__ import annotations

import argparse

from sqlalchemy.exc import SQLAlchemyError

from docker_agent.agent.router import AgentRoutingError
from docker_agent.agent.service import AgentTurnResult, DockerSupportAgent
from docker_agent.rag.answer import CitationValidationError
from docker_agent.tools.docker_cli import DockerToolTimeout


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Docker support agent with docs and read-only runtime evidence."
    )
    parser.add_argument("question")
    return parser.parse_args()


def print_turn(result: AgentTurnResult) -> None:
    decision = result.decision
    print(f"Route: {decision.route}")
    print(f"Reason: {decision.reason}")
    print(f"Use docs: {decision.use_docs}")

    if result.needs_clarification:
        print(f"\n{decision.clarification}")
        return

    assert result.answer is not None
    answer = result.answer

    print("\nAnswer\n")
    print(answer.answer)

    if answer.cited_runtime_sources:
        print("\nRuntime evidence")
        for source in answer.cited_runtime_sources:
            command = " ".join(source.command)
            status = "success" if source.ok else "error"
            print(f"[R{source.index}] {source.tool} ({status})")
            print(f"    {command}")

    if answer.cited_doc_sources:
        print("\nDocker Docs")
        for source in answer.cited_doc_sources:
            section = f" > {source.section}" if source.section else ""
            print(f"[{source.index}] {source.title}{section}")
            print(f"    {source.source_url}")

    if answer.docs_context_truncated or answer.runtime_context_truncated:
        print("\nNote: one or more evidence contexts were truncated to configured limits.")


def main() -> None:
    args = parse_args()

    try:
        agent = DockerSupportAgent()
        result = agent.handle(args.question)
    except AgentRoutingError as exc:
        raise SystemExit(f"Unsafe/invalid route decision: {exc}") from None
    except CitationValidationError as exc:
        raise SystemExit(f"Invalid model citation: {exc}") from None
    except DockerToolTimeout as exc:
        raise SystemExit(str(exc)) from None
    except SQLAlchemyError:
        raise SystemExit(
            "PostgreSQL is unavailable. Start Docker Desktop and run "
            "docker compose up -d postgres, then retry."
        ) from None
    except ValueError as exc:
        raise SystemExit(str(exc)) from None

    print_turn(result)


if __name__ == "__main__":
    main()
