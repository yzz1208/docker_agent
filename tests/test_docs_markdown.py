from docker_agent.docs.markdown import (
    clean_markdown,
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
