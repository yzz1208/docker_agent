from pathlib import Path

from docker_agent.docs.pipeline import build_dataset


def test_build_dataset_filters_navigation_and_exact_duplicates(tmp_path: Path) -> None:
    selected = tmp_path / "selected"
    output = tmp_path / "processed"

    first = selected / "content/get-started/first.md"
    second = selected / "content/get-started/second.md"
    first.parent.mkdir(parents=True, exist_ok=True)

    shared_content = (
        "Docker containers package an application with its runtime dependencies so the same "
        "workload can run consistently across development, testing, and deployment environments "
        "without relying on machine-specific library installations or local configuration."
    )

    first.write_text(
        f"""---
title: First page
---
# First page

## Shared concept

{shared_content}

## Next steps

* [Containers](/engine/containers/)
* [Networking](/engine/network/)
""",
        encoding="utf-8",
    )
    second.write_text(
        f"""---
title: Second page
---
# Second page

## Repeated concept

{shared_content}
""",
        encoding="utf-8",
    )

    documents, chunks = build_dataset(selected, output)

    assert len(documents) == 2
    assert len(chunks) == 1
    assert chunks[0].content == shared_content
    assert (output / "documents.jsonl").exists()
    assert (output / "chunks.jsonl").exists()
