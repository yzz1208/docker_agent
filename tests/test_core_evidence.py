import pytest

from docker_agent.core.evidence import (
    Evidence,
    EvidenceBundle,
    EvidenceKind,
    citation_source_to_evidence,
    runtime_tool_result_to_evidence,
    user_message_to_evidence,
)
from docker_agent.core.tool_result import ToolErrorType, ToolResult
from docker_agent.rag.context import CitationSource


def _runtime_result(
    *,
    ok: bool = True,
    output: str = "64MiB",
    error: str | None = None,
    error_type: ToolErrorType = ToolErrorType.NONE,
) -> ToolResult:
    return ToolResult(
        tool_name="docker_stats",
        ok=ok,
        output=output,
        error=error,
        error_type=error_type,
        metadata={
            "adapter": "docker_cli",
            "command": ("docker", "stats", "web"),
            "returncode": 0 if ok else 1,
        },
    )


def _citation_source() -> CitationSource:
    return CitationSource(
        index=2,
        chunk_id="chunk-abc",
        title="Docker volumes",
        section_path=("Storage", "Volumes"),
        source_url="https://docs.docker.com/engine/storage/volumes/",
        file_path="content/manuals/engine/storage/volumes.md",
    )


def test_runtime_tool_result_to_evidence_preserves_runtime_label() -> None:
    evidence = runtime_tool_result_to_evidence(_runtime_result(), index=1)

    assert evidence.kind is EvidenceKind.RUNTIME
    assert evidence.source == "docker_stats"
    assert evidence.content == "64MiB"
    assert evidence.ok is True
    assert evidence.citation_label == "[R1]"
    assert evidence.metadata["error_type"] == "none"
    assert evidence.evidence_id.startswith("ev_")


def test_failed_runtime_result_uses_error_as_evidence_content() -> None:
    evidence = runtime_tool_result_to_evidence(
        _runtime_result(
            ok=False,
            output="",
            error="permission denied",
            error_type=ToolErrorType.PERMISSION_DENIED,
        ),
        index=1,
    )

    assert evidence.ok is False
    assert evidence.content == "permission denied"
    assert evidence.metadata["error_type"] == "permission_denied"


def test_runtime_evidence_id_is_stable_for_same_input() -> None:
    first = runtime_tool_result_to_evidence(_runtime_result(), index=1)
    second = runtime_tool_result_to_evidence(_runtime_result(), index=1)

    assert first.evidence_id == second.evidence_id


def test_citation_source_to_evidence_preserves_doc_metadata() -> None:
    evidence = citation_source_to_evidence(
        _citation_source(),
        content="Volumes are managed by Docker.",
    )

    assert evidence.kind is EvidenceKind.KNOWLEDGE
    assert evidence.source == "docker_docs"
    assert evidence.citation_label == "[2]"
    assert evidence.metadata["chunk_id"] == "chunk-abc"
    assert evidence.metadata["section_path"] == ("Storage", "Volumes")


def test_user_message_to_evidence_has_no_citation_label() -> None:
    evidence = user_message_to_evidence(
        "这个容器刚刚被我手动停止了。",
    )

    assert evidence.kind is EvidenceKind.USER
    assert evidence.source == "user_message"
    assert evidence.citation_label is None
    assert evidence.ok is True


def test_evidence_bundle_rejects_duplicate_ids() -> None:
    evidence = user_message_to_evidence("same")

    with pytest.raises(ValueError, match="duplicate evidence_id"):
        EvidenceBundle(
            items=(evidence, evidence),
            text="same",
        )


def test_evidence_bundle_rejects_duplicate_citation_labels() -> None:
    first = Evidence(
        evidence_id="ev_1",
        kind=EvidenceKind.RUNTIME,
        source="docker_stats",
        content="one",
        ok=True,
        citation_label="[R1]",
    )
    second = Evidence(
        evidence_id="ev_2",
        kind=EvidenceKind.RUNTIME,
        source="docker_logs",
        content="two",
        ok=True,
        citation_label="[R1]",
    )

    with pytest.raises(ValueError, match="duplicate citation labels"):
        EvidenceBundle(
            items=(first, second),
            text="one\ntwo",
        )


def test_runtime_evidence_requires_positive_index() -> None:
    with pytest.raises(ValueError, match="index must be positive"):
        runtime_tool_result_to_evidence(_runtime_result(), index=0)


def test_failed_runtime_evidence_preserves_partial_stdout_before_stderr() -> None:
    result = ToolResult(
        tool_name="docker_logs",
        ok=False,
        output="partial stdout",
        error="permission denied",
        error_type=ToolErrorType.PERMISSION_DENIED,
    )

    evidence = runtime_tool_result_to_evidence(result, index=1)

    assert evidence.content == "partial stdout"
    assert evidence.metadata["error_type"] == "permission_denied"
