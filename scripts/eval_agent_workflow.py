from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from docker_agent.agent.router import AgentRoutingError
from docker_agent.agent.service import DockerSupportAgent
from docker_agent.agent.workflow_evaluation import (
    WorkflowEvalMetrics,
    concept_coverage,
    summarize_workflow_metrics,
)
from docker_agent.config import get_settings
from docker_agent.rag.answer import CitationValidationError
from docker_agent.rag.context import CitationSource, RagContext
from docker_agent.rag.llm import OpenAICompatibleChatClient
from docker_agent.tools.docker_cli import DockerToolResult

DEFAULT_INPUT = Path("data/eval/agent_workflow_v1.jsonl")
DEFAULT_OUTPUT = Path("reports/agent_workflow_eval_latest.jsonl")


class ScenarioDockerTools:
    """Return deterministic runtime evidence without touching the local Docker daemon."""

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
            "Evaluate the full Docker support agent with synthetic runtime evidence. "
            "No real Docker commands are executed."
        )
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=None)
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
        text = str(item.get("content") or "").strip()

        section = " > ".join(section_path)
        header = [f"[{index}]", f"Title: {title}"]
        if section:
            header.append(f"Section: {section}")
        if source_url:
            header.append(f"Source: {source_url}")
        header.extend(["Content:", text])
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
    if not args.input.exists():
        raise SystemExit(f"Workflow evaluation file not found: {args.input}")
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be positive")

    rows = _load_rows(args.input)
    if args.limit is not None:
        rows = rows[: args.limit]
    if not rows:
        raise SystemExit("Workflow evaluation file contains no cases")

    router_model = _model(temperature=0.0)
    answer_model = _model(temperature=0.0)
    metrics: list[WorkflowEvalMetrics] = []
    output_rows: list[dict[str, Any]] = []

    for row in rows:
        case_id = str(row.get("id") or "").strip()
        question = str(row.get("question") or "").strip()
        expected = row.get("expected")
        runtime = row.get("runtime", {})

        if not case_id or not question:
            raise ValueError("Each workflow case requires id and question")
        if not isinstance(expected, dict):
            raise TypeError(f"Case {case_id} expected must be an object")
        if not isinstance(runtime, dict):
            raise TypeError(f"Case {case_id} runtime must be an object")

        expected_route = str(expected.get("route") or "")
        expected_tools_raw = expected.get("tools", [])
        if not isinstance(expected_tools_raw, list):
            raise TypeError(f"Case {case_id} expected tools must be a list")
        expected_tools = frozenset(str(tool) for tool in expected_tools_raw)
        expected_use_docs = expected.get("use_docs")
        if not isinstance(expected_use_docs, bool):
            raise TypeError(f"Case {case_id} expected use_docs must be boolean")

        docs_context = _docs_context(row.get("docs"))
        docker_tools = ScenarioDockerTools(runtime)
        required = _required_groups(row.get("required_concepts"))

        agent = DockerSupportAgent(
            router_model=router_model,
            answer_model=answer_model,
            docker_tools=docker_tools,  # type: ignore[arg-type]
            docs_retriever=lambda _question, context=docs_context: context,
        )

        error: str | None = None
        result = None
        try:
            result = agent.handle(question)
        except (AgentRoutingError, CitationValidationError, ValueError) as exc:
            error = str(exc)

        completed = result is not None and result.answer is not None
        route_match = result is not None and result.decision.route == expected_route
        tool_match = frozenset(docker_tools.calls) == expected_tools

        runtime_citation_ok = expected_route != "runtime_tools"
        docs_citation_ok = not expected_use_docs
        coverage = 0.0
        answer_text = ""

        if result is not None and result.answer is not None:
            answer_text = result.answer.answer
            if expected_route == "runtime_tools":
                runtime_citation_ok = bool(result.answer.runtime_citation_indices)
            if expected_use_docs:
                docs_citation_ok = bool(result.answer.doc_citation_indices)
            coverage = concept_coverage(answer_text, required)

        case_metrics = WorkflowEvalMetrics(
            case_id=case_id,
            completed=completed,
            route_match=route_match,
            tool_call_exact_match=tool_match,
            runtime_citation_present=runtime_citation_ok,
            docs_citation_present=docs_citation_ok,
            concept_coverage=coverage,
        )
        metrics.append(case_metrics)

        actual_route = result.decision.route if result is not None else None
        actual_use_docs = result.decision.use_docs if result is not None else None

        output_row: dict[str, Any] = {
            "id": case_id,
            "question": question,
            "expected": {
                "route": expected_route,
                "tools": sorted(expected_tools),
                "use_docs": expected_use_docs,
            },
            "actual": {
                "route": actual_route,
                "tools_called": docker_tools.calls,
                "use_docs": actual_use_docs,
            },
            "metrics": {
                "completed": case_metrics.completed,
                "route_match": case_metrics.route_match,
                "tool_call_exact_match": case_metrics.tool_call_exact_match,
                "runtime_citation_present": case_metrics.runtime_citation_present,
                "docs_citation_present": case_metrics.docs_citation_present,
                "concept_coverage": case_metrics.concept_coverage,
                "exact_workflow_match": case_metrics.exact_workflow_match,
            },
            "answer": answer_text,
        }
        if error is not None:
            output_row["error"] = error
        output_rows.append(output_row)

        print(
            f"[{case_id}] complete={case_metrics.completed} "
            f"route={case_metrics.route_match} "
            f"tools={case_metrics.tool_call_exact_match} "
            f"concepts={case_metrics.concept_coverage:.2f} "
            f"workflow={case_metrics.exact_workflow_match}"
        )

        if not case_metrics.exact_workflow_match:
            print(f"  expected tools={sorted(expected_tools)}")
            print(f"  actual tools={docker_tools.calls}")
            print(f"  expected route={expected_route} actual route={actual_route}")
            if error:
                print(f"  error={error}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in output_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = {
        "cases": len(rows),
        "summary": summarize_workflow_metrics(metrics),
        "output": str(args.output),
        "note": (
            "Synthetic runtime evidence is used. No local Docker command is executed. "
            "Docs evidence is synthetic so this evaluates orchestration and answer grounding, "
            "not retrieval quality."
        ),
    }

    print("\nSummary")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
