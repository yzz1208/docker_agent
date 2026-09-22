import pytest

from docker_agent.rag.answer import (
    CitationValidationError,
    extract_citation_indices,
    generate_grounded_answer,
    select_cited_sources,
)
from docker_agent.rag.context import CitationSource, RagContext


class FakeModel:
    def __init__(self, answer: str = "先检查 daemon 是否运行。[1]") -> None:
        self.answer = answer
        self.system_prompt = ""
        self.user_prompt = ""

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return self.answer


def _source(index: int) -> CitationSource:
    return CitationSource(
        index=index,
        chunk_id=f"chunk-{index}",
        title=f"Source {index}",
        section_path=("Daemon",),
        source_url=f"https://docs.docker.com/source-{index}/",
        file_path=f"source-{index}.md",
    )


def test_extract_citation_indices_preserves_first_appearance_order() -> None:
    assert extract_citation_indices("先看 [2]，再看 [1]，最后还是 [2]。") == (2, 1)


def test_select_cited_sources_rejects_unknown_labels() -> None:
    with pytest.raises(CitationValidationError, match=r"\[3\]"):
        select_cited_sources("Unsupported citation [3]", (_source(1), _source(2)))


def test_generate_grounded_answer_passes_numbered_context_to_model() -> None:
    context = RagContext(
        text="[1]\nTitle: Troubleshooting\nContent:\nStart the daemon.",
        sources=(_source(1),),
        truncated=False,
    )
    model = FakeModel()

    result = generate_grounded_answer("Docker daemon 连不上怎么办？", context, model)

    assert result.answer.endswith("[1]")
    assert "[1]" in model.user_prompt
    assert "Docker daemon 连不上怎么办？" in model.user_prompt
    assert "only" in model.system_prompt.lower()
    assert result.sources[0].title == "Source 1"
    assert result.citation_indices == (1,)
    assert result.cited_sources == (_source(1),)


def test_generate_grounded_answer_tracks_used_sources_in_numeric_order() -> None:
    context = RagContext(
        text="[1] one\n\n[2] two\n\n[3] three",
        sources=(_source(1), _source(2), _source(3)),
        truncated=False,
    )
    model = FakeModel("结论来自第二和第一条资料。[2][1]")

    result = generate_grounded_answer("test", context, model)

    assert result.citation_indices == (2, 1)
    assert [source.index for source in result.cited_sources] == [1, 2]
