from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from docker_agent.agent.dynamic_evaluation import (
    DynamicWorkflowEvalMetrics,
    summarize_dynamic_workflow_metrics,
)
from docker_agent.agent.dynamic_planner import DynamicPlannerError
from docker_agent.agent.dynamic_service import DynamicDockerSupportAgent
from docker_agent.agent.evidence import build_runtime_evidence
from docker_agent.agent.dynamic_workflow import DynamicWorkflowError
from docker_agent.agent.router import AgentRoutingError
from docker_agent.agent.workflow_evaluation import (
    concept_coverage,
    missing_concept_groups,
)
from docker_agent.agent.workflow_judge import (
    judge_workflow_answer,
    summarize_workflow_judges,
)
from docker_agent.config import get_settings
from docker_agent.rag.answer import CitationValidationError
from docker_agent.rag.context import CitationSource, RagContext
from docker_agent.rag.llm import ModelRequestError, OpenAICompatibleChatClient
from docker_agent.tools.docker_cli import DockerToolResult, DockerToolTimeout

DEFAULT_INPUT = Path("data/eval/dynamic_workflow_v1.jsonl")
DEFAULT_OUTPUT = Path("reports/dynamic_workflow_eval_latest.jsonl")


class ScenarioDockerTools:
    """Deterministic Docker evidence provider that never touches the local daemon."""

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
            "Evaluate observe-decide-act Docker workflows with synthetic runtime evidence. "
            "No local Docker commands are executed."
        )
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Run the evidence-grounded answer judge after dynamic workflow completion.",
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


def main() -> None:
    args = parse_args()
    settings = get_settings()

    if not args.input.exists():
        raise SystemExit(f"Dynamic workflow evaluation file not found: {args.input}")
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be positive")

    rows = _load_rows(args.input)
    if args.limit is not None:
        rows = rows[: args.limit]
    if not rows:
        raise SystemExit("Dynamic workflow evaluation file contains no cases")

    router_model = _model(temperature=0.0)
    planner_model = _model(temperature=0.0)
    answer_model = _model(temperature=0.0)
    judge_model = _model(temperature=0.0) if args.judge else None

    metrics: list[DynamicWorkflowEvalMetrics] = []
    judge_results = []
    judge_issue_cases: list[dict[str, Any]] = []
    output_rows: list[dict[str, Any]] = []

    for row in rows:
        case_id = str(row.get("id") or "").strip()
        question = str(row.get("question") or "").strip()
        expected = row.get("expected")
        runtime = row.get("runtime", {})

        if not case_id or not question:
            raise ValueError("Each dynamic workflow case requires id and question")
        if not isinstance(expected, dict):
            raise TypeError(f"Case {case_id} expected must be an object")
        if not isinstance(runtime, dict):
            raise TypeError(f"Case {case_id} runtime must be an object")

        expected_route = str(expected.get("route") or "")
        expected_sequence_raw = expected.get("tool_sequence", [])
        if not isinstance(expected_sequence_raw, list):
            raise TypeError(f"Case {case_id} expected tool_sequence must be a list")
        expected_sequence = [str(tool) for tool in expected_sequence_raw]
        expected_use_docs = expected.get("use_docs")
        if not isinstance(expected_use_docs, bool):
            raise TypeError(f"Case {case_id} expected use_docs must be boolean")

        docs_context = _docs_context(row.get("docs"))
        required = _required_groups(row.get("required_concepts"))
        docker_tools = ScenarioDockerTools(runtime)

        agent = DynamicDockerSupportAgent(
            settings=settings,
            router_model=router_model,
            planner_model=planner_model,
            answer_model=answer_model,
            docker_tools=docker_tools,  # type: ignore[arg-type]
            docs_retriever=lambda _question, context=docs_context: context,
        )

        result = None
        error: str | None = None
        try:
            result = agent.handle(question)
        except (
            AgentRoutingError,
            DynamicPlannerError,
            DynamicWorkflowError,
            CitationValidationError,
            ModelRequestError,
            ValueError,
        ) as exc:
            error = str(exc)

        completed = result is not None and result.answer is not None
        route_match = result is not None and result.decision.route == expected_route
        tool_sequence_match = docker_tools.calls == expected_sequence

        trace = result.runtime_trace if result is not None else ()
        runtime_expected = expected_route == "runtime_tools"
        finish_present = (
            not runtime_expected
            or bool(trace)
            and trace[-1].decision.action == "finish"
        )
        step_limit_ok = len(trace) <= settings.dynamic_runtime_max_steps
        no_repeated_tools = len(docker_tools.calls) == len(set(docker_tools.calls))

        runtime_citation_ok = not runtime_expected
        docs_citation_ok = not expected_use_docs
        answer_text = ""
        coverage = 0.0

        if result is not None and result.answer is not None:
            answer_text = result.answer.answer
            if runtime_expected:
                runtime_citation_ok = bool(result.answer.runtime_citation_indices)
            if expected_use_docs:
                docs_citation_ok = bool(result.answer.doc_citation_indices)
            coverage = concept_coverage(answer_text, required)

        case_metrics = DynamicWorkflowEvalMetrics(
            case_id=case_id,
            completed=completed,
            route_match=route_match,
            tool_sequence_match=tool_sequence_match,
            finish_present=finish_present,
            step_limit_ok=step_limit_ok,
            no_repeated_tools=no_repeated_tools,
            runtime_citation_present=runtime_citation_ok,
            docs_citation_present=docs_citation_ok,
            concept_coverage=coverage,
        )
        metrics.append(case_metrics)

        missing = missing_concept_groups(answer_text, required)
        trace_rows = [
            {
                "step": step.step,
                "action": step.decision.action,
                "tool": step.decision.tool,
                "reason": step.decision.reason,
                "tool_ok": step.result.ok if step.result is not None else None,
            }
            for step in trace
        ]

        output_row: dict[str, Any] = {
            "id": case_id,
            "question": question,
            "expected": {
                "route": expected_route,
                "tool_sequence": expected_sequence,
                "use_docs": expected_use_docs,
            },
            "actual": {
                "route": result.decision.route if result is not None else None,
                "tool_sequence": docker_tools.calls,
                "trace": trace_rows,
                "use_docs": result.decision.use_docs if result is not None else None,
            },
            "metrics": {
                "completed": case_metrics.completed,
                "route_match": case_metrics.route_match,
                "tool_sequence_match": case_metrics.tool_sequence_match,
                "finish_present": case_metrics.finish_present,
                "step_limit_ok": case_metrics.step_limit_ok,
                "no_repeated_tools": case_metrics.no_repeated_tools,
                "runtime_citation_present": case_metrics.runtime_citation_present,
                "docs_citation_present": case_metrics.docs_citation_present,
                "concept_coverage": case_metrics.concept_coverage,
                "missing_concepts": [list(group) for group in missing],
                "exact_dynamic_workflow_match": (
                    case_metrics.exact_dynamic_workflow_match
                ),
            },
            "answer": answer_text,
        }
        if error is not None:
            output_row["error"] = error

        if judge_model is not None and completed:
            try:
                observed_results = tuple(
                    step.result
                    for step in trace
                    if step.result is not None
                )
                observed_evidence = build_runtime_evidence(
                    observed_results,
                    max_chars=settings.runtime_evidence_max_chars,
                )
                judged = judge_workflow_answer(
                    question=question,
                    answer=answer_text,
                    runtime_evidence=observed_evidence.text,
                    docs_evidence=docs_context.text,
                    model=judge_model,
                )
            except (ModelRequestError, json.JSONDecodeError, TypeError, ValueError) as exc:
                output_row["judge_error"] = str(exc)
            else:
                judge_results.append(judged)
                output_row["judge"] = {
                    "groundedness": judged.groundedness,
                    "runtime_citation_correctness": (
                        judged.runtime_citation_correctness
                    ),
                    "docs_citation_correctness": judged.docs_citation_correctness,
                    "diagnosis_quality": judged.diagnosis_quality,
                    "unsupported_claims": list(judged.unsupported_claims),
                    "rationale": judged.rationale,
                }
                has_judge_issue = (
                    judged.groundedness < 5
                    or judged.runtime_citation_correctness < 5
                    or judged.docs_citation_correctness < 5
                    or judged.diagnosis_quality < 5
                    or bool(judged.unsupported_claims)
                )
                if has_judge_issue:
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
                    print("  judge diagnostics:")
                    print(f"    groundedness={judged.groundedness}/5")
                    print(
                        "    runtime_citation_correctness="
                        f"{judged.runtime_citation_correctness}/5"
                    )
                    print(
                        "    docs_citation_correctness="
                        f"{judged.docs_citation_correctness}/5"
                    )
                    print(f"    diagnosis_quality={judged.diagnosis_quality}/5")
                    if judged.unsupported_claims:
                        print(
                            "    unsupported_claims="
                            f"{list(judged.unsupported_claims)}"
                        )
                    if judged.rationale:
                        print(f"    rationale={judged.rationale}")

        output_rows.append(output_row)

        print(
            f"[{case_id}] complete={case_metrics.completed} "
            f"route={case_metrics.route_match} "
            f"sequence={case_metrics.tool_sequence_match} "
            f"finish={case_metrics.finish_present} "
            f"concepts={case_metrics.concept_coverage:.2f} "
            f"workflow={case_metrics.exact_dynamic_workflow_match}"
        )

        if not case_metrics.exact_dynamic_workflow_match:
            print(f"  expected sequence={expected_sequence}")
            print(f"  actual sequence={docker_tools.calls}")
            if trace_rows:
                print(f"  trace={trace_rows}")
            if missing:
                print(f"  missing concepts={[list(group) for group in missing]}")
            if error:
                print(f"  error={error}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in output_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary: dict[str, Any] = {
        "cases": len(rows),
        "summary": summarize_dynamic_workflow_metrics(metrics),
        "output": str(args.output),
        "note": (
            "Synthetic runtime evidence is used. No local Docker command is executed. "
            "This evaluates observation-driven planning plus final grounded answers."
        ),
    }
    if judge_model is not None:
        summary["judge"] = summarize_workflow_judges(judge_results)
        summary["judge_errors"] = sum(
            1 for row in output_rows if "judge_error" in row
        )
        summary["judge_issue_cases"] = judge_issue_cases

    print("\nSummary")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
