from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError

from docker_agent.agent.conversation import AgentConversation
from docker_agent.agent.router import AgentRoutingError
from docker_agent.agent.service import AgentTurnResult, DockerSupportAgent
from docker_agent.rag.answer import CitationValidationError
from docker_agent.tools.docker_cli import DockerToolTimeout


def print_turn(result: AgentTurnResult) -> None:
    decision = result.decision
    print(f"\nRoute: {decision.route}")
    print(f"Reason: {decision.reason}")
    print(f"Use docs: {decision.use_docs}")

    if result.needs_clarification:
        print(f"\nAgent: {decision.clarification}")
        return

    assert result.answer is not None
    answer = result.answer

    print(f"\nAgent:\n{answer.answer}")

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


def main() -> None:
    try:
        conversation = AgentConversation(DockerSupportAgent())
    except ValueError as exc:
        raise SystemExit(str(exc)) from None

    print("Docker Support Agent")
    print("Commands: /reset clears pending clarification, /exit quits.")

    while True:
        try:
            user_message = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return

        if not user_message:
            continue
        if user_message.lower() in {"/exit", "/quit"}:
            print("Bye.")
            return
        if user_message.lower() == "/reset":
            conversation.reset()
            print("Pending clarification state cleared.")
            continue

        try:
            result = conversation.handle(user_message)
        except AgentRoutingError as exc:
            print(f"\nAgent error: unsafe/invalid route decision: {exc}")
            continue
        except CitationValidationError as exc:
            print(f"\nAgent error: invalid model citation: {exc}")
            continue
        except DockerToolTimeout as exc:
            print(f"\nAgent error: {exc}")
            continue
        except SQLAlchemyError:
            print(
                "\nAgent error: PostgreSQL is unavailable. Start Docker Desktop and run "
                "docker compose up -d postgres."
            )
            continue
        except ValueError as exc:
            print(f"\nAgent error: {exc}")
            continue

        print_turn(result)


if __name__ == "__main__":
    main()
