from docker_agent.rag.text import build_embedding_text


def test_build_embedding_text_includes_metadata_and_content() -> None:
    text = build_embedding_text(
        title="Troubleshoot Docker daemon",
        section_path=["Engine", "Daemon", "Troubleshooting"],
        content="Run docker info to check daemon connectivity.",
    )

    assert "Document: Troubleshoot Docker daemon" in text
    assert "Section: Engine > Daemon > Troubleshooting" in text
    assert "docker info" in text
