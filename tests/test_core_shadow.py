from docker_agent.agent.core_shadow import build_core_shadow_report
from docker_agent.agent.dynamic_planner import DynamicRuntimeDecision
from docker_agent.agent.dynamic_workflow import DynamicRuntimeStep
from docker_agent.agent.evidence import build_runtime_evidence
from docker_agent.agent.router import AgentRouteDecision
from docker_agent.rag.context import CitationSource, RagContext
from docker_agent.tools.docker_cli import DockerToolResult


def _decision(*, use_docs: bool = False) -> AgentRouteDecision:
    return AgentRouteDecision(
        route="runtime_tools",
        reason="runtime evidence required",
        container_ref="web",
        tools=("docker_stats",),
        clarification=None,
        use_docs=use_docs,
    )


def _result() -> DockerToolResult:
    return DockerToolResult(
        tool="docker_stats",
        command=("docker", "stats", "--no-stream", "web"),
        returncode=0,
        stdout='{"MemUsage":"64MiB"}',
        stderr="",
    )


def _trace(result: DockerToolResult) -> tuple[DynamicRuntimeStep, ...]:
    return (
        DynamicRuntimeStep(
            step=1,
            decision=DynamicRuntimeDecision(
                action="tool",
                tool="docker_stats",
                reason="Measure current memory.",
            ),
            result=result,
        ),
        DynamicRuntimeStep(
            step=2,
            decision=DynamicRuntimeDecision(
                action="finish",
                tool=None,
                reason="Measurement is sufficient.",
            ),
            result=None,
        ),
    )


def test_core_shadow_report_matches_legacy_runtime_path() -> None:
    result = _result()
    runtime_context = build_runtime_evidence((result,), max_chars=8_000)

    report = build_core_shadow_report(
        question="web 现在用了多少内存？",
        decision=_decision(),
        runtime_results=(result,),
        runtime_context=runtime_context,
        docs_context=RagContext(text="", sources=(), truncated=False),
        runtime_trace=_trace(result),
        answer="web 当前使用 64MiB。[R1]",
    )

    assert report.ok is True
    assert report.issues == ()
    assert report.state.route == "runtime_tools"
    assert report.state.container_ref == "web"
    assert len(report.state.tool_results) == 1
    assert len(report.state.evidence) == 1
    assert report.state.evidence[0].citation_label == "[R1]"
    assert len(report.state.runtime_steps) == 2
    assert report.state.answer == "web 当前使用 64MiB。[R1]"


def test_core_shadow_report_combines_runtime_and_docs_evidence() -> None:
    result = _result()
    runtime_context = build_runtime_evidence((result,), max_chars=8_000)
    docs = RagContext(
        text=(
            "[1]\n"
            "Title: Resource constraints\n"
            "Source: https://docs.docker.com/engine/containers/resource_constraints/\n"
            "Content:\n"
            "Docker can limit container memory."
        ),
        sources=(
            CitationSource(
                index=1,
                chunk_id="memory-limit",
                title="Resource constraints",
                section_path=(),
                source_url=(
                    "https://docs.docker.com/engine/containers/"
                    "resource_constraints/"
                ),
                file_path="resource_constraints.md",
            ),
        ),
        truncated=False,
    )

    report = build_core_shadow_report(
        question="web 内存怎么样，官方怎么限制？",
        decision=_decision(use_docs=True),
        runtime_results=(result,),
        runtime_context=runtime_context,
        docs_context=docs,
        runtime_trace=_trace(result),
        answer="当前 64MiB [R1]；Docker 支持内存限制 [1]。",
    )

    assert report.ok is True
    assert len(report.runtime_bundle.items) == 1
    assert len(report.docs_bundle.items) == 1
    assert [item.citation_label for item in report.state.evidence] == [
        "[R1]",
        "[1]",
    ]


def test_core_shadow_report_detects_runtime_content_drift() -> None:
    result = _result()
    runtime_context = build_runtime_evidence((result,), max_chars=8_000)
    drifted_context = type(runtime_context)(
        text=runtime_context.text.replace("64MiB", "65MiB"),
        sources=runtime_context.sources,
        truncated=runtime_context.truncated,
    )

    report = build_core_shadow_report(
        question="web 现在用了多少内存？",
        decision=_decision(),
        runtime_results=(result,),
        runtime_context=drifted_context,
        docs_context=RagContext(text="", sources=(), truncated=False),
        runtime_trace=_trace(result),
        answer="web 当前使用 64MiB。[R1]",
    )

    assert report.ok is False
    assert "runtime evidence 1 content changed" in report.issues
