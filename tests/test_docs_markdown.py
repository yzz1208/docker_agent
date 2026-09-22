from docker_agent.docs.markdown import (
    clean_markdown,
    is_low_value_chunk,
    parse_front_matter,
    source_url_from_path,
    split_section_content,
    split_sections,
)

SAMPLE = """---
title: Troubleshooting Docker
---

# Troubleshooting Docker

Intro paragraph.

## Check the daemon

Run this command:

```bash
docker info
# this is a shell comment, not a Markdown heading
```

{{< tip >}}
Keep the exact error message.
{{< /tip >}}
"""


def test_front_matter_and_heading_split() -> None:
    metadata, body = parse_front_matter(SAMPLE)
    cleaned = clean_markdown(body)
    sections = split_sections(cleaned, fallback_title=str(metadata["title"]))

    assert metadata["title"] == "Troubleshooting Docker"
    assert len(sections) == 2
    assert sections[0].section_path == ["Troubleshooting Docker"]
    assert sections[1].section_path == ["Troubleshooting Docker", "Check the daemon"]
    assert "docker info" in sections[1].content
    assert "shell comment" in sections[1].content
    assert "{{< tip >}}" not in cleaned
    assert "Keep the exact error message." in cleaned


def test_inline_shortcodes_are_removed_outside_code_fences() -> None:
    body = """Use {{< badge >}}Docker{{< /badge >}} here.

```text
{{< literal-example >}}
```
"""

    cleaned = clean_markdown(body)

    assert "Use Docker here." in cleaned
    assert "{{< literal-example >}}" in cleaned


def test_longer_outer_fence_keeps_inner_triple_fence_and_headings_literal() -> None:
    body = """# Root

## Example

````markdown
```bash
# not a Markdown heading
docker info
```
````

## Next

Continue here.
"""

    sections = split_sections(body, fallback_title="Root")

    # The H1 has no body text of its own, so split_sections intentionally emits
    # only sections that contain content: Example and Next.
    assert len(sections) == 2
    assert sections[0].section_path == ["Root", "Example"]
    assert "# not a Markdown heading" in sections[0].content
    assert sections[1].section_path == ["Root", "Next"]


def test_low_value_filter_targets_navigation_but_keeps_commands() -> None:
    link_list = (
        "* [Multi-stage builds](/build/building/multi-stage/) "
        "* [Base images](/build/building/base-images/)"
    )

    assert is_low_value_chunk(link_list)
    assert is_low_value_chunk("Now that you understand volumes, continue to networking.")
    assert not is_low_value_chunk("docker info")


def test_source_url_mapping() -> None:
    assert source_url_from_path("content/manuals/engine/daemon/troubleshoot.md") == (
        "https://docs.docker.com/engine/daemon/troubleshoot/"
    )
    assert source_url_from_path("content/get-started/_index.md") == (
        "https://docs.docker.com/get-started/"
    )


def test_long_sections_are_split() -> None:
    content = " ".join(f"word{i}" for i in range(1000))
    chunks = split_section_content(content, max_words=200, overlap_words=20)

    assert len(chunks) > 1
    assert all(chunk.strip() for chunk in chunks)


def test_chunk_overlap_does_not_copy_code_fence_markers() -> None:
    intro = " ".join(f"intro{i}" for i in range(60))
    code_lines = "\n".join(f"log line {i}" for i in range(30))
    tail = " ".join(f"tail{i}" for i in range(60))
    content = f"{intro}\n\n```console\n{code_lines}\n```\n\n{tail}"

    chunks = split_section_content(content, max_words=130, overlap_words=20)

    assert len(chunks) >= 2
    for chunk in chunks:
        fence_lines = [line for line in chunk.splitlines() if line.lstrip().startswith("```")]
        assert len(fence_lines) % 2 == 0
