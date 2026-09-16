from __future__ import annotations

import subprocess
from pathlib import Path

REPO_URL = "https://github.com/docker/docs.git"
TARGET = Path("data/raw/docker-docs")


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)

    if (TARGET / ".git").exists():
        print(f"Updating existing Docker Docs repository: {TARGET}")
        run("git", "-C", str(TARGET), "fetch", "--depth", "1", "origin", "main")
        run("git", "-C", str(TARGET), "reset", "--hard", "origin/main")
    elif TARGET.exists():
        raise SystemExit(
            f"{TARGET} already exists but is not a Git repository. Remove it and retry."
        )
    else:
        print(f"Cloning Docker Docs into: {TARGET}")
        run("git", "clone", "--depth", "1", "--branch", "main", REPO_URL, str(TARGET))

    print("Docker Docs source is ready.")


if __name__ == "__main__":
    main()
