from __future__ import annotations

import argparse

from docker_agent.tools.docker_cli import DockerReadOnlyTools, DockerToolTimeout


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run allowlisted read-only Docker diagnostic commands."
    )
    subparsers = parser.add_subparsers(dest="tool", required=True)

    subparsers.add_parser("info", help="Show Docker daemon/system information")
    ps_parser = subparsers.add_parser("ps", help="List containers")
    ps_parser.add_argument(
        "--running-only",
        action="store_true",
        help="Exclude stopped containers.",
    )

    inspect_parser = subparsers.add_parser("inspect", help="Inspect one container")
    inspect_parser.add_argument("container")

    logs_parser = subparsers.add_parser("logs", help="Show recent container logs")
    logs_parser.add_argument("container")
    logs_parser.add_argument("--tail", type=int, default=100)

    stats_parser = subparsers.add_parser("stats", help="Show one resource snapshot")
    stats_parser.add_argument("container")

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tools = DockerReadOnlyTools()

    try:
        if args.tool == "info":
            result = tools.info()
        elif args.tool == "ps":
            result = tools.ps(include_stopped=not args.running_only)
        elif args.tool == "inspect":
            result = tools.inspect(args.container)
        elif args.tool == "logs":
            result = tools.logs(args.container, tail=args.tail)
        elif args.tool == "stats":
            result = tools.stats(args.container)
        else:
            raise SystemExit(f"Unsupported diagnostic tool: {args.tool}")
    except (ValueError, DockerToolTimeout) as exc:
        raise SystemExit(str(exc)) from None

    if result.output:
        print(result.output)

    if not result.ok:
        raise SystemExit(result.returncode or 1)


if __name__ == "__main__":
    main()
