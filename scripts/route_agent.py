from __future__ import annotations

import argparse
import json

from docker_agent.agent.router import AgentRoutingError, route_question
from docker_agent.agent.runtime import execute_runtime_plan
from docker_agent.config import get_settings
from docker_agent.rag.llm import OpenAICompatibleChatClient
from docker_agent.tools.docker_cli import DockerReadOnlyTools, DockerToolTimeout


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Route a Docker support question to docs, runtime tools, or clarification."
    )
    parser.add_argument("question")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute a validated read-only runtime plan.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    if not settings.model_name.strip() or not settings.model_base_url.strip():
        raise SystemExit("MODEL_NAME and MODEL_BASE_URL must be configured in .env")

    model = OpenAICompatibleChatClient(
        model=settings.model_name,
        base_url=settings.model_base_url,
        api_key=settings.model_api_key,
        timeout_seconds=settings.model_timeout_seconds,
        temperature=0.0,
    )
    try:
        decision = route_question(args.question, model)
    except AgentRoutingError as exc:
        raise SystemExit(f"Unsafe/invalid route decision: {exc}") from None

    print(
        json.dumps(
            {
                "route": decision.route,
                "reason": decision.reason,
                "container_ref": decision.container_ref,
                "tools": list(decision.tools),
                "clarification": decision.clarification,
                "use_docs": decision.use_docs,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if not args.execute:
        return

    if decision.route == "clarify":
        print(f"\nClarification\n{decision.clarification}")
        return
    if decision.route == "docs_only":
        print("\nNo runtime command executed; this question should use Docker Docs RAG.")
        return

    runtime_tools = DockerReadOnlyTools()
    try:
        results = execute_runtime_plan(decision, runtime_tools)
    except (ValueError, DockerToolTimeout) as exc:
        raise SystemExit(str(exc)) from None

    print("\nRuntime evidence")
    for result in results:
        print(f"\n[{result.tool}] returncode={result.returncode}")
        print(result.output or "<no output>")


if __name__ == "__main__":
    main()
