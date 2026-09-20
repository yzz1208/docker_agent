import pytest

from docker_agent.agent.core_adapters import (
    dynamic_step_to_agent_step,
    dynamic_trace_to_agent_steps,
    rag_context_to_evidence_bundle,
    runtime_context_to_evidence_bundle,
)
from docker_agent.agent.dynamic_planner import DynamicRuntimeDecision
from docker_agent.agent.dynamic_workflow import DynamicRuntimeStep
from docker_agent.agent.evidence import RuntimeEvidenceContext, RuntimeEvidenceSource
from docker_agent.core.evidence import EvidenceKind
from docker_agent.rag.context import CitationSource, RagContext
from docker_agent.tools.docker_cli import DockerToolResult


def test_runtime_context_to_evidence_bundle_preserves_legacy_view() -> None:
    context = RuntimeEvidenceContext(
        text=(
            "[R1]\n"
            "Tool: docker_stats\n"
            "Command: docker stats --no-stream web\n"
            "Status: success\n"
            "Output:\n"
            '{"MemUsage":"64MiB"}'
        ),
        sources=(
            RuntimeEvidenceSource(
                index=1,
                tool="docker_stats",
                command=("docker", "stats", "--no-stream", "web"),
                ok=True,
            ),
        ),
        truncated=False,
    )

    bundle = runtime_context_to_evidence_bundle(context)

    assert bundle.text == context.text
    assert bundle.truncated is False
    assert len(bundle.items) == 1
    assert bundle.items[0].kind is EvidenceKind.RUNTIME
    assert bundle.items[0].citation_label == "[R1]"
    assert bundle.items[0].content == '{"MemUsage":"64MiB"}'
    assert bundle.items[0].metadata["legacy_status"] == "success"


def test_runtime_context_adapter_preserves_failure_observation() -> None:
    context = RuntimeEvidenceContext(
        text=(
            "[R1]\n"
            "Tool: docker_info\n"
            "Command: docker info\n"
            "Status: error(returncode=1)\n"
            "Output:\n"
            "permission denied"
        ),
        sources=(
            RuntimeEvidenceSource(
                index=1,
                tool="docker_info",
                command=("docker", "info"),
                ok=False,
            ),
        ),
        truncated=False,
    )

    bundle = runtime_context_to_evidence_bundle(context)

    assert bundle.items[0].ok is False
    assert bundle.items[0].content == "permission denied"
    assert bundle.items[0].metadata["legacy_status"] == "error(returncode=1)"


def test_rag_context_to_evidence_bundle_preserves_doc_metadata() -> None:
    context = RagContext(
        text=(
            "[1]\n"
            "Title: Volumes\n"
            "Section: Storage > Volumes\n"
            "Source: https://docs.docker.com/engine/storage/volumes/\n"
            "Content:\n"
            "Volumes are managed by Docker."
        ),
        sources=(
            CitationSource(
                index=1,
                chunk_id="chunk-volumes",
                title="Volumes",
                section_path=("Storage", "Volumes"),
                source_url="https://docs.docker.com/engine/storage/volumes/",
                file_path="content/manuals/engine/storage/volumes.md",
            ),
        ),
        truncated=False,
    )

    bundle = rag_context_to_evidence_bundle(context)

    assert bundle.text == context.text
    assert bundle.items[0].kind is EvidenceKind.KNOWLEDGE
    assert bundle.items[0].citation_label == "[1]"
    assert bundle.items[0].content == "Volumes are managed by Docker."
    assert bundle.items[0].metadata["chunk_id"] == "chunk-volumes"


def test_context_adapters_reject_source_block_mismatch() -> None:
    context = RagContext(
        text="[1]\nTitle: One\nContent:\nOne",
        sources=(
            CitationSource(
                index=1,
                chunk_id="one",
                title="One",
                section_path=(),
                source_url="https://example.test/one",
                file_path="one.md",
            ),
            CitationSource(
                index=2,
                chunk_id="two",
                title="Two",
                section_path=(),
                source_url="https://example.test/two",
                file_path="two.md",
            ),
        ),
        truncated=False,
    )

    with pytest.raises(ValueError, match="source count"):
        rag_context_to_evidence_bundle(context)


def test_empty_contexts_convert_to_empty_bundles() -> None:
    runtime = runtime_context_to_evidence_bundle(
        RuntimeEvidenceContext(text="", sources=(), truncated=False)
    )
    docs = rag_context_to_evidence_bundle(
        RagContext(text="", sources=(), truncated=False)
    )

    assert runtime.items == ()
    assert docs.items == ()


def test_dynamic_step_to_agent_step_preserves_decision_and_result_status() -> None:
    step = DynamicRuntimeStep(
        step=1,
        decision=DynamicRuntimeDecision(
            action="tool",
            tool="docker_inspect",
            reason="Inspect state first.",
        ),
        result=DockerToolResult(
            tool="docker_inspect",
            command=("docker", "inspect", "web"),
            returncode=0,
            stdout='{"State":{"Status":"exited"}}',
            stderr="",
        ),
    )

    converted = dynamic_step_to_agent_step(step)

    assert converted.index == 1
    assert converted.action == "tool"
    assert converted.tool_name == "docker_inspect"
    assert converted.reason == "Inspect state first."
    assert converted.ok is True


def test_dynamic_trace_to_agent_steps_preserves_finish_step() -> None:
    finish = DynamicRuntimeStep(
        step=2,
        decision=DynamicRuntimeDecision(
            action="finish",
            tool=None,
            reason="Evidence is sufficient.",
        ),
        result=None,
    )

    converted = dynamic_trace_to_agent_steps((finish,))

    assert len(converted) == 1
    assert converted[0].action == "finish"
    assert converted[0].tool_name is None
    assert converted[0].ok is None
