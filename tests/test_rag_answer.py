from docker_agent.rag.answer import generate_grounded_answer
from docker_agent.rag.context import CitationSource, RagContext


class FakeModel:
    def __init__(self) -> None:
        self.system_prompt = ""
        self.user_prompt = ""

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return "先检查 daemon 是否运行。[1]"


def test_generate_grounded_answer_passes_numbered_context_to_model() -> None:
    context = RagContext(
        text="[1]\nTitle: Troubleshooting\nContent:\nStart the daemon.",
        sources=(
            CitationSource(
                index=1,
                chunk_id="chunk-1",
                title="Troubleshooting",
                section_path=("Daemon",),
                source_url="https://docs.docker.com/engine/daemon/troubleshoot/",
                file_path="troubleshoot.md",
            ),
        ),
        truncated=False,
    )
    model = FakeModel()

    result = generate_grounded_answer("Docker daemon 连不上怎么办？", context, model)

    assert result.answer.endswith("[1]")
    assert "[1]" in model.user_prompt
    assert "Docker daemon 连不上怎么办？" in model.user_prompt
    assert "only" in model.system_prompt.lower()
    assert result.sources[0].title == "Troubleshooting"
