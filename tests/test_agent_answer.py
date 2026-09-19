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


class SequenceModel:
    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        self.prompts.append(user_prompt)
        return self.answers.pop(0)


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


def test_generate_agent_answer_repairs_invalid_doc_citation_once() -> None:
    model = SequenceModel(
        [
            "当前使用 64MiB。[R1] 这是 Docker 的标准行为。[1]",
            "当前使用 64MiB。[R1]",
        ]
    )

    result = generate_agent_answer(
        "web 现在用了多少内存？",
        RagContext(text="", sources=(), truncated=False),
        _runtime_context(),
        model,
    )

    assert result.answer == "当前使用 64MiB。[R1]"
    assert result.doc_citation_indices == ()
    assert result.runtime_citation_indices == (1,)
    assert len(model.prompts) == 2
    assert "failed citation validation" in model.prompts[1]


def test_agent_prompt_lists_available_citation_labels() -> None:
    prompt = build_agent_user_prompt(
        "web 现在用了多少内存？",
        RagContext(text="", sources=(), truncated=False),
        _runtime_context(),
    )

    assert "Docker Docs: <none>" in prompt
    assert "Runtime: [R1]" in prompt


def test_agent_prompt_forbids_unprovided_background_knowledge() -> None:
    prompt = build_agent_user_prompt(
        "Docker volume 和 bind mount 有什么区别？",
        _docs_context(),
        RuntimeEvidenceContext(text="", sources=(), truncated=False),
    )

    assert "do not add general Docker knowledge" in prompt


def test_agent_prompt_treats_exit_codes_as_observations_without_docs() -> None:
    prompt = build_agent_user_prompt(
        "web-prod 为什么退出了？",
        RagContext(text="", sources=(), truncated=False),
        _runtime_context(),
    )

    assert "Raw exit codes are observations" in prompt
    assert "do not explain what an exit code generally means" in prompt


def test_agent_prompt_does_not_transfer_candidate_state_to_missing_target() -> None:
    prompt = build_agent_user_prompt(
        "web-prod 为什么退出了？",
        RagContext(text="", sources=(), truncated=False),
        _runtime_context(),
    )

    assert "similar names from docker_ps are only candidates" in prompt
    assert "Do not attribute their state or failure reason" in prompt
