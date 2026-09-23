from __future__ import annotations

from docker_agent.orchestration.checkpoint import (
    open_postgres_orchestration_checkpointer,
)


def main() -> None:
    with open_postgres_orchestration_checkpointer(setup=True):
        pass
    print("LangGraph orchestration checkpoint tables are ready.")


if __name__ == "__main__":
    main()
