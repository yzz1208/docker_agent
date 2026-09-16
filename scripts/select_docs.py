from pathlib import Path

from docker_agent.docs.pipeline import DEFAULT_INCLUDE_PREFIXES, select_markdown_files


RAW_REPO = Path("data/raw/docker-docs")
SELECTED_ROOT = Path("data/selected/docker-docs")


def main() -> None:
    copied = select_markdown_files(RAW_REPO, SELECTED_ROOT)

    print("Selected Docker Docs prefixes:")
    for prefix in DEFAULT_INCLUDE_PREFIXES:
        print(f"  - {prefix}")
    print(f"Copied {len(copied)} Markdown files to {SELECTED_ROOT}")


if __name__ == "__main__":
    main()
