from docker_agent.deployment import production_preflight


def main() -> int:
    return production_preflight()


if __name__ == "__main__":
    raise SystemExit(main())
