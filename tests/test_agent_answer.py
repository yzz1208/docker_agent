import pytest

from docker_agent.agent.answer import (
    build_agent_user_prompt,
    generate_agent_answer,
)
from docker_agent.agent.evidence import RuntimeEvidenceContext, RuntimeEvidenceSource
from docker_agent.rag.answer import CitationValidationError
from docker_agent.rag.context import CitationSource, RagContext


class FakeModel:
    def __init__(self, answer: str) -> None:
        self.answer = answer

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        assert "runtime evidence" in system_prompt.lower()
        assert "Docker documentation evidence" in user_prompt
        return self.answer


def _docs_context() -> RagContext:
    return RagContext(
        text="[1]\nTitle: Stats\nContent:\nUse docker stats.",
        sources=(
            CitationSource(
                index=1,
                chunk_id="chunk-1",
                title="Stats",
                section_path=("Runtime metrics",),
                source_url="https://docs.docker.com/engine/containers/runmetrics/",
                file_path="runmetrics.md",
            ),
        ),
        truncated=False,
    )


def _runtime_context() -> RuntimeEvidenceContext:
    return RuntimeEvidenceContext(
        text=(
            "[R1]\nTool: docker_stats\nCommand: docker stats web\n"
            "Status: success\nOutput:\n"
            '{"MemUsage":"64MiB / 1GiB"}'
        ),
        sources=(
            RuntimeEvidenceSource(
                index=1,
                tool="docker_stats",
                command=("docker", "stats", "web"),
                ok=True,
            ),
        ),
        truncated=False,
    )


def test_generate_agent_answer_tracks_doc_and_runtime_citations() -> None:
    result = generate_agent_answer(
        "web 现在用了多少内存？",
        _docs_context(),
        _runtime_context(),
        FakeModel("当前内存使用约 64MiB。[R1] 可用 docker stats 查看运行指标。[1]"),
    )

    assert result.runtime_citation_indices == (1,)
    assert result.doc_citation_indices == (1,)
    assert result.cited_runtime_sources[0].tool == "docker_stats"
    assert result.cited_doc_sources[0].title == "Stats"


def test_generate_agent_answer_rejects_unknown_runtime_citation() -> None:
    with pytest.raises(CitationValidationError, match=r"\[R2\]"):
        generate_agent_answer(
            "web 现在用了多少内存？",
            _docs_context(),
            _runtime_context(),
            FakeModel("当前使用 64MiB。[R2]"),
        )


def test_build_agent_prompt_allows_docs_only_evidence() -> None:
    prompt = build_agent_user_prompt(
        "volume 是什么？",
        _docs_context(),
        RuntimeEvidenceContext(text="", sources=(), truncated=False),
    )

    assert "<no local runtime evidence>" in prompt
    assert "[1]" in prompt
