from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from docker_agent.agent.dynamic_planner import DynamicPlannerError
from docker_agent.agent.dynamic_service import DynamicDockerSupportAgent
from docker_agent.agent.dynamic_workflow import DynamicRuntimeStep, DynamicWorkflowError
from docker_agent.agent.router import AgentRoutingError
from docker_agent.agent.workflow_evaluation import concept_coverage
from docker_agent.agent.workflow_judge import (
    judge_workflow_answer,
    summarize_workflow_judges,
)
from docker_agent.config import get_settings
from docker_agent.graph.evaluation import GraphParityMetrics, summarize_graph_parity
from docker_agent.graph.service import LangGraphDockerSupportAgent
from docker_agent.rag.answer import CitationValidationError
from docker_agent.rag.context import CitationSource, RagContext
from docker_agent.rag.llm import ModelRequestError, OpenAICompatibleChatClient
from docker_agent.tools.docker_cli import DockerToolResult, DockerToolTimeout

DEFAULT_INPUT = Path("data/eval/dynamic_workflow_v1.jsonl")
DEFAULT_OUTPUT = Path("reports/langgraph_parity_latest.jsonl")


class ScenarioDockerTools:
    """Deterministic read-only Docker evidence; never touches the local daemon."""

    def __init__(self, runtime: dict[str, Any]) -> None:
        self.runtime = runtime
        self.calls: list[str] = []

    def info(self) -> DockerToolResult:
        return self._result("docker_info", ("docker", "info"))

    def ps(self, *, include_stopped: bool = True) -> DockerToolResult:
        command = ("docker", "ps", "--all") if include_stopped else ("docker", "ps")
        return self._result("docker_ps", command)

    def inspect(self, container: str) -> DockerToolResult:
        return self._result("docker_inspect", ("docker", "inspect", container))

    def logs(self, container: str, *, tail: int = 100) -> DockerToolResult:
        return self._result(
            "docker_logs",
            ("docker", "logs", "--tail", str(tail), container),
        )

    def stats(self, container: str) -> DockerToolResult:
        return self._result(
            "docker_stats",
            ("docker", "stats", "--no-stream", container),
        )

    def _result(self, tool: str, command: tuple[str, ...]) -> DockerToolResult:
        self.calls.append(tool)
        raw = self.runtime.get(tool)
        if not isinstance(raw, dict):
            return DockerToolResult(
                tool=tool,
                command=command,
                returncode=1,
                stdout="",
                stderr=f"Scenario does not define output for {tool}",
            )

        if raw.get("timeout") is True:
            message = str(
                raw.get("message")
                or f"{tool} timed out while collecting runtime evidence"
            )
            raise DockerToolTimeout(message)

        return DockerToolResult(
            tool=tool,
            command=command,
            returncode=int(raw.get("returncode", 0)),
            stdout=str(raw.get("stdout") or ""),
            stderr=str(raw.get("stderr") or ""),
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare the legacy dynamic agent with the LangGraph coarse workflow "
            "using synthetic Docker evidence. No local Docker commands are executed."
        )
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Judge LangGraph answers against the evidence actually supplied to the graph.",
    )
    return parser.parse_args()


def _model(*, temperature: float) -> OpenAICompatibleChatClient:
    settings = get_settings()
    if not settings.model_name.strip() or not settings.model_base_url.strip():
        raise SystemExit("MODEL_NAME and MODEL_BASE_URL must be configured in .env")

    return OpenAICompatibleChatClient(
        model=settings.model_name,
        base_url=settings.model_base_url,
        api_key=settings.model_api_key,
        timeout_seconds=settings.model_timeout_seconds,
        temperature=temperature,
        max_retries=settings.model_max_retries,
        retry_backoff_seconds=settings.model_retry_backoff_seconds,
    )


def _load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise TypeError(f"Expected object at {path}:{line_number}")
            rows.append(row)
    return rows


def _docs_context(raw_docs: Any) -> RagContext:
    if raw_docs is None:
        raw_docs = []
    if not isinstance(raw_docs, list):
        raise TypeError("docs must be a list")

    blocks: list[str] = []
    sources: list[CitationSource] = []
    for index, item in enumerate(raw_docs, start=1):
        if not isinstance(item, dict):
            raise TypeError("each docs entry must be an object")

        title = str(item.get("title") or f"Document {index}")
        section_path_raw = item.get("section_path", [])
        if not isinstance(section_path_raw, list):
            raise TypeError("section_path must be a list")
        section_path = tuple(str(part) for part in section_path_raw)
        source_url = str(item.get("source_url") or "")
        file_path = str(item.get("file_path") or f"synthetic-{index}.md")
        body = str(item.get("content") or "").strip()

        section = " > ".join(section_path)
        header = [f"[{index}]", f"Title: {title}"]
        if section:
            header.append(f"Section: {section}")
        if source_url:
            header.append(f"Source: {source_url}")
        header.extend(["Content:", body])
        blocks.append("\n".join(header))

        sources.append(
            CitationSource(
                index=index,
                chunk_id=f"synthetic-{index}",
                title=title,
                section_path=section_path,
                source_url=source_url,
                file_path=file_path,
            )
        )

    return RagContext(
        text="\n\n---\n\n".join(blocks),
        sources=tuple(sources),
        truncated=False,
    )


def _required_groups(raw: Any) -> tuple[tuple[str, ...], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise TypeError("required_concepts must be a list")

    groups: list[tuple[str, ...]] = []
    for group in raw:
        if not isinstance(group, list) or not group:
            raise TypeError("each required_concepts item must be a non-empty list")
        groups.append(tuple(str(item) for item in group))
    return tuple(groups)


def _trace_signature(
    trace: tuple[DynamicRuntimeStep, ...],
) -> list[tuple[str, str | None, bool | None]]:
    return [
        (
            step.decision.action,
            step.decision.tool,
            step.result.ok if step.result is not None else None,
        )
        for step in trace
    ]


def _expected_match(
    *,
    route: str | None,
    use_docs: bool | None,
    calls: list[str],
    answer_text: str,
    runtime_citations: tuple[int, ...],
    doc_citations: tuple[int, ...],
    expected_route: str,
    expected_use_docs: bool,
    expected_sequence: list[str],
    required: tuple[tuple[str, ...], ...],
) -> bool:
    if route != expected_route or use_docs != expected_use_docs:
        return False
    if calls != expected_sequence:
        return False
    if expected_route == "runtime_tools" and not runtime_citations:
        return False
    if expected_use_docs and not doc_citations:
        return False
    return concept_coverage(answer_text, required) == 1.0


def main() -> None:
    args = parse_args()
    settings = get_settings()

    if not args.input.exists():
        raise SystemExit(f"Parity evaluation file not found: {args.input}")
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be positive")

    rows = _load_rows(args.input)
    if args.limit is not None:
        rows = rows[: args.limit]
    if not rows:
        raise SystemExit("Parity evaluation file contains no cases")

    router_model = _model(temperature=0.0)
    planner_model = _model(temperature=0.0)
    answer_model = _model(temperature=0.0)
    judge_model = _model(temperature=0.0) if args.judge else None

    metrics: list[GraphParityMetrics] = []
    judge_results = []
    judge_issue_cases: list[dict[str, Any]] = []
    judge_error_cases: list[dict[str, str]] = []
    expected_issue_cases: list[dict[str, Any]] = []
    output_rows: list[dict[str, Any]] = []

    handled_errors = (
        AgentRoutingError,
        DynamicPlannerError,
        DynamicWorkflowError,
        CitationValidationError,
        ModelRequestError,
        ValueError,
    )

    for row in rows:
        case_id = str(row.get("id") or "").strip()
        question = str(row.get("question") or "").strip()
        expected = row.get("expected")
        runtime = row.get("runtime", {})

        if not case_id or not question:
            raise ValueError("Each parity case requires id and question")
        if not isinstance(expected, dict):
            raise TypeError(f"Case {case_id} expected must be an object")
        if not isinstance(runtime, dict):
            raise TypeError(f"Case {case_id} runtime must be an object")

        expected_route = str(expected.get("route") or "")
        expected_use_docs = expected.get("use_docs")
        if not isinstance(expected_use_docs, bool):
            raise TypeError(f"Case {case_id} expected use_docs must be boolean")
        expected_sequence_raw = expected.get("tool_sequence", [])
        if not isinstance(expected_sequence_raw, list):
            raise TypeError(f"Case {case_id} expected tool_sequence must be a list")
        expected_sequence = [str(item) for item in expected_sequence_raw]

        docs_context = _docs_context(row.get("docs"))
        required = _required_groups(row.get("required_concepts"))
        legacy_tools = ScenarioDockerTools(runtime)
        graph_tools = ScenarioDockerTools(runtime)

        legacy_agent = DynamicDockerSupportAgent(
            settings=settings,
            router_model=router_model,
            planner_model=planner_model,
            answer_model=answer_model,
            docker_tools=legacy_tools,  # type: ignore[arg-type]
            docs_retriever=lambda _question, context=docs_context: context,
        )
        graph_agent = LangGraphDockerSupportAgent(
            settings=settings,
            router_model=router_model,
            planner_model=planner_model,
            answer_model=answer_model,
            docker_tools=graph_tools,  # type: ignore[arg-type]
            docs_retriever=lambda _question, context=docs_context: context,
        )

        legacy_result = None
        legacy_error: str | None = None
        try:
            legacy_result = legacy_agent.handle(question)
        except handled_errors as exc:
            legacy_error = str(exc)

        graph_state = None
        graph_error: str | None = None
        try:
            graph_state = graph_agent.handle_graph(question)
        except handled_errors as exc:
            graph_error = str(exc)

        legacy_decision = legacy_result.decision if legacy_result is not None else None
        graph_decision = graph_state["decision"] if graph_state is not None else None
        legacy_answer = legacy_result.answer if legacy_result is not None else None
        graph_answer = graph_state["answer"] if graph_state is not None else None
        legacy_trace = legacy_result.runtime_trace if legacy_result is not None else ()
        graph_trace = graph_state["runtime_trace"] if graph_state is not None else ()

        legacy_answer_text = legacy_answer.answer if legacy_answer is not None else ""
        graph_answer_text = graph_answer.answer if graph_answer is not None else ""
        legacy_runtime_citations = (
            legacy_answer.runtime_citation_indices if legacy_answer is not None else ()
        )
        graph_runtime_citations = (
            graph_answer.runtime_citation_indices if graph_answer is not None else ()
        )
        legacy_doc_citations = (
            legacy_answer.doc_citation_indices if legacy_answer is not None else ()
        )
        graph_doc_citations = (
            graph_answer.doc_citation_indices if graph_answer is not None else ()
        )

        graph_labels: list[str] = []
        if graph_state is not None:
            graph_labels = [
                item.citation_label
                for item in graph_state["agent_state"].evidence
                if item.citation_label is not None
            ]
        expected_graph_labels = [
            *[f"[R{index}]" for index in range(1, len(graph_tools.calls) + 1)],
            *(
                [f"[{index}]" for index in range(1, len(docs_context.sources) + 1)]
                if graph_decision is not None and graph_decision.use_docs
                else []
            ),
        ]

        legacy_expected = _expected_match(
            route=legacy_decision.route if legacy_decision is not None else None,
            use_docs=legacy_decision.use_docs if legacy_decision is not None else None,
            calls=legacy_tools.calls,
            answer_text=legacy_answer_text,
            runtime_citations=legacy_runtime_citations,
            doc_citations=legacy_doc_citations,
            expected_route=expected_route,
            expected_use_docs=expected_use_docs,
            expected_sequence=expected_sequence,
            required=required,
        )
        graph_expected = _expected_match(
            route=graph_decision.route if graph_decision is not None else None,
            use_docs=graph_decision.use_docs if graph_decision is not None else None,
            calls=graph_tools.calls,
            answer_text=graph_answer_text,
            runtime_citations=graph_runtime_citations,
            doc_citations=graph_doc_citations,
            expected_route=expected_route,
            expected_use_docs=expected_use_docs,
            expected_sequence=expected_sequence,
            required=required,
        )

        if not legacy_expected or not graph_expected:
            expected_issue_cases.append(
                {
                    "id": case_id,
                    "legacy_expected": legacy_expected,
                    "graph_expected": graph_expected,
                    "legacy_concept_coverage": concept_coverage(
                        legacy_answer_text,
                        required,
                    ),
                    "graph_concept_coverage": concept_coverage(
                        graph_answer_text,
                        required,
                    ),
                    "legacy_tool_sequence": legacy_tools.calls,
                    "graph_tool_sequence": graph_tools.calls,
                    "required_concepts": [list(group) for group in required],
                }
            )

        case_metrics = GraphParityMetrics(
            case_id=case_id,
            route_parity=(
                legacy_decision is not None
                and graph_decision is not None
                and legacy_decision.route == graph_decision.route
            ),
            container_ref_parity=(
                legacy_decision is not None
                and graph_decision is not None
                and legacy_decision.container_ref == graph_decision.container_ref
            ),
            use_docs_parity=(
                legacy_decision is not None
                and graph_decision is not None
                and legacy_decision.use_docs == graph_decision.use_docs
            ),
            tool_sequence_parity=legacy_tools.calls == graph_tools.calls,
            trace_parity=(
                _trace_signature(legacy_trace) == _trace_signature(graph_trace)
            ),
            citation_parity=(
                legacy_runtime_citations == graph_runtime_citations
                and legacy_doc_citations == graph_doc_citations
            ),
            clarification_parity=(
                legacy_decision is not None
                and graph_decision is not None
                and legacy_decision.clarification == graph_decision.clarification
            ),
            graph_evidence_labels_match=graph_labels == expected_graph_labels,
            legacy_expected_match=legacy_expected,
            graph_expected_match=graph_expected,
        )
        metrics.append(case_metrics)

        output_row: dict[str, Any] = {
            "id": case_id,
            "question": question,
            "expected": {
                "route": expected_route,
                "tool_sequence": expected_sequence,
                "use_docs": expected_use_docs,
            },
            "legacy": {
                "route": legacy_decision.route if legacy_decision else None,
                "container_ref": (
                    legacy_decision.container_ref if legacy_decision else None
                ),
                "use_docs": legacy_decision.use_docs if legacy_decision else None,
                "tool_sequence": legacy_tools.calls,
                "trace": _trace_signature(legacy_trace),
                "runtime_citations": list(legacy_runtime_citations),
                "doc_citations": list(legacy_doc_citations),
                "concept_coverage": concept_coverage(
                    legacy_answer_text,
                    required,
                ),
                "error": legacy_error,
            },
            "graph": {
                "route": graph_decision.route if graph_decision else None,
                "container_ref": (
                    graph_decision.container_ref if graph_decision else None
                ),
                "use_docs": graph_decision.use_docs if graph_decision else None,
                "tool_sequence": graph_tools.calls,
                "trace": _trace_signature(graph_trace),
                "runtime_citations": list(graph_runtime_citations),
                "doc_citations": list(graph_doc_citations),
                "concept_coverage": concept_coverage(
                    graph_answer_text,
                    required,
                ),
                "evidence_labels": graph_labels,
                "error": graph_error,
            },
            "parity": {
                "route": case_metrics.route_parity,
                "container_ref": case_metrics.container_ref_parity,
                "use_docs": case_metrics.use_docs_parity,
                "tool_sequence": case_metrics.tool_sequence_parity,
                "trace": case_metrics.trace_parity,
                "citation": case_metrics.citation_parity,
                "clarification": case_metrics.clarification_parity,
                "evidence_labels": case_metrics.graph_evidence_labels_match,
                "legacy_expected": case_metrics.legacy_expected_match,
                "graph_expected": case_metrics.graph_expected_match,
                "exact": case_metrics.exact_parity,
            },
        }

        if judge_model is not None and graph_answer is not None and graph_state is not None:
            runtime_context = graph_state["runtime_context"]
            graph_docs_context = graph_state["docs_context"]
            runtime_evidence = (
                runtime_context.text if runtime_context is not None else ""
            )
            docs_evidence = (
                graph_docs_context.text if graph_docs_context is not None else ""
            )
            try:
                judged = judge_workflow_answer(
                    question=question,
                    answer=graph_answer_text,
                    runtime_evidence=runtime_evidence,
                    docs_evidence=docs_evidence,
                    model=judge_model,
                )
            except (ModelRequestError, json.JSONDecodeError, TypeError, ValueError) as exc:
                judge_error = str(exc)
                output_row["graph_judge_error"] = judge_error
                judge_error_cases.append(
                    {
                        "id": case_id,
                        "error": judge_error,
                    }
                )
                print(f"  graph judge error={judge_error}")
            else:
                judge_results.append(judged)
                output_row["graph_judge"] = {
                    "groundedness": judged.groundedness,
                    "runtime_citation_correctness": (
                        judged.runtime_citation_correctness
                    ),
                    "docs_citation_correctness": judged.docs_citation_correctness,
                    "diagnosis_quality": judged.diagnosis_quality,
                    "unsupported_claims": list(judged.unsupported_claims),
                    "rationale": judged.rationale,
                }
                has_issue = (
                    judged.groundedness < 5
                    or judged.runtime_citation_correctness < 5
                    or judged.docs_citation_correctness < 5
                    or judged.diagnosis_quality < 5
                    or bool(judged.unsupported_claims)
                )
                if has_issue:
                    issue = {
                        "id": case_id,
                        "groundedness": judged.groundedness,
                        "runtime_citation_correctness": (
                            judged.runtime_citation_correctness
                        ),
                        "docs_citation_correctness": (
                            judged.docs_citation_correctness
                        ),
                        "diagnosis_quality": judged.diagnosis_quality,
                        "unsupported_claims": list(judged.unsupported_claims),
                        "rationale": judged.rationale,
                    }
                    judge_issue_cases.append(issue)
                    print(
                        "  graph judge issue="
                        f"{json.dumps(issue, ensure_ascii=False)}"
                    )

        output_rows.append(output_row)

        print(
            f"[{case_id}] parity={case_metrics.exact_parity} "
            f"legacy_expected={legacy_expected} graph_expected={graph_expected} "
            f"route={case_metrics.route_parity} "
            f"tools={case_metrics.tool_sequence_parity} "
            f"trace={case_metrics.trace_parity} "
            f"citations={case_metrics.citation_parity} "
            f"evidence={case_metrics.graph_evidence_labels_match}"
        )
        if legacy_error:
            print(f"  legacy error={legacy_error}")
        if graph_error:
            print(f"  graph error={graph_error}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in output_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary: dict[str, Any] = {
        "cases": len(rows),
        "parity": summarize_graph_parity(metrics),
        "expected_issue_cases": expected_issue_cases,
        "output": str(args.output),
        "note": (
            "Legacy and LangGraph agents use the same models and synthetic Docker/docs "
            "evidence. No local Docker command is executed."
        ),
    }
    if judge_model is not None:
        summary["graph_judge"] = summarize_workflow_judges(judge_results)
        summary["graph_judge_errors"] = len(judge_error_cases)
        summary["graph_judge_error_cases"] = judge_error_cases
        summary["graph_judge_issue_cases"] = judge_issue_cases

    print("\nSummary")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
