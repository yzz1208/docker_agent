from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any

from docker_agent.agent.dynamic_planner import DynamicPlannerError
from docker_agent.agent.dynamic_workflow import (
    DynamicRuntimeResult,
    DynamicWorkflowError,
    run_dynamic_runtime_workflow,
)
from docker_agent.agent.router import route_question
from docker_agent.config import get_settings
from docker_agent.graph.runtime_loop import run_runtime_loop_graph
from docker_agent.rag.llm import ModelRequestError, OpenAICompatibleChatClient
from docker_agent.tools.docker_cli import DockerToolResult, DockerToolTimeout

DEFAULT_INPUT = Path("data/eval/dynamic_workflow_v1.jsonl")
DEFAULT_OUTPUT = Path("reports/runtime_loop_parity_latest.jsonl")


class ScenarioDockerTools:
    """Synthetic read-only Docker tools; no local daemon command is executed."""

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


class RecordingModel:
    """Delegate to the real planner once and record raw decisions for replay."""

    def __init__(self, delegate: OpenAICompatibleChatClient) -> None:
        self.delegate = delegate
        self.responses: list[str] = []

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        response = self.delegate.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        self.responses.append(response)
        return response


class ReplayModel:
    """Replay legacy planner decisions so graph parity is framework-only."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.index = 0

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        if self.index >= len(self.responses):
            raise RuntimeError("Graph requested more planner decisions than legacy loop")
        response = self.responses[self.index]
        self.index += 1
        return response


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare legacy and node-level LangGraph runtime loops with identical "
            "planner decisions and synthetic Docker evidence."
        )
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


def _model(*, temperature: float = 0.0) -> OpenAICompatibleChatClient:
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


def _result_signature(
    result: DynamicRuntimeResult | None,
) -> list[tuple[Any, ...]]:
    if result is None:
        return []
    return [
        (
            item.tool,
            item.command,
            item.returncode,
            item.stdout,
            item.stderr,
        )
        for item in result.results
    ]


def _trace_signature(
    result: DynamicRuntimeResult | None,
) -> list[tuple[Any, ...]]:
    if result is None:
        return []
    return [
        (
            step.step,
            step.decision.action,
            step.decision.tool,
            step.decision.reason,
            step.result.returncode if step.result is not None else None,
        )
        for step in result.trace
    ]


def _error_signature(exc: Exception | None) -> tuple[str, str] | None:
    if exc is None:
        return None
    return (type(exc).__name__, str(exc))


def _rate(values: list[bool]) -> float:
    if not values:
        return 0.0
    return mean(1.0 if value else 0.0 for value in values)


def main() -> None:
    args = parse_args()
    settings = get_settings()

    if not args.input.exists():
        raise SystemExit(f"Runtime loop evaluation file not found: {args.input}")
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be positive")

    rows = _load_rows(args.input)
    runtime_rows = [
        row
        for row in rows
        if isinstance(row.get("expected"), dict)
        and row["expected"].get("route") == "runtime_tools"
    ]
    if args.limit is not None:
        runtime_rows = runtime_rows[: args.limit]
    if not runtime_rows:
        raise SystemExit("No runtime_tools cases found in evaluation file")

    router_model = _model()
    planner_model = _model()

    parity_rows: list[dict[str, Any]] = []
    route_ok_values: list[bool] = []
    tool_parity_values: list[bool] = []
    result_parity_values: list[bool] = []
    trace_parity_values: list[bool] = []
    evidence_parity_values: list[bool] = []
    error_parity_values: list[bool] = []
    exact_values: list[bool] = []
    legacy_expected_values: list[bool] = []
    graph_expected_values: list[bool] = []

    handled_errors = (
        DynamicPlannerError,
        DynamicWorkflowError,
        ModelRequestError,
        ValueError,
        RuntimeError,
    )

    for row in runtime_rows:
        case_id = str(row.get("id") or "").strip()
        question = str(row.get("question") or "").strip()
        runtime = row.get("runtime")
        expected = row.get("expected")

        if not case_id or not question:
            raise ValueError("Each runtime loop case requires id and question")
        if not isinstance(runtime, dict):
            raise TypeError(f"Case {case_id} runtime must be an object")
        if not isinstance(expected, dict):
            raise TypeError(f"Case {case_id} expected must be an object")

        expected_tools_raw = expected.get("tool_sequence", [])
        if not isinstance(expected_tools_raw, list):
            raise TypeError(f"Case {case_id} expected tool_sequence must be a list")
        expected_tools = [str(item) for item in expected_tools_raw]

        route = route_question(question, router_model)
        route_ok = route.route == "runtime_tools"
        route_ok_values.append(route_ok)

        legacy_tools = ScenarioDockerTools(runtime)
        graph_tools = ScenarioDockerTools(runtime)
        recorder = RecordingModel(planner_model)

        legacy_result: DynamicRuntimeResult | None = None
        legacy_error: Exception | None = None
        if route_ok:
            try:
                legacy_result = run_dynamic_runtime_workflow(
                    question=question,
                    route=route,
                    planner_model=recorder,
                    docker_tools=legacy_tools,  # type: ignore[arg-type]
                    max_steps=settings.dynamic_runtime_max_steps,
                    evidence_max_chars=settings.runtime_evidence_max_chars,
                )
            except handled_errors as exc:
                legacy_error = exc

        graph_result: DynamicRuntimeResult | None = None
        graph_error: Exception | None = None
        if route_ok:
            replay = ReplayModel(recorder.responses)
            try:
                graph_result = run_runtime_loop_graph(
                    question=question,
                    route=route,
                    planner_model=replay,
                    docker_tools=graph_tools,  # type: ignore[arg-type]
                    max_steps=settings.dynamic_runtime_max_steps,
                    evidence_max_chars=settings.runtime_evidence_max_chars,
                )
            except handled_errors as exc:
                graph_error = exc

        tool_parity = legacy_tools.calls == graph_tools.calls
        result_parity = _result_signature(legacy_result) == _result_signature(
            graph_result
        )
        trace_parity = _trace_signature(legacy_result) == _trace_signature(
            graph_result
        )

        legacy_evidence = (
            (
                legacy_result.evidence.text,
                legacy_result.evidence.truncated,
            )
            if legacy_result is not None
            else None
        )
        graph_evidence = (
            (
                graph_result.evidence.text,
                graph_result.evidence.truncated,
            )
            if graph_result is not None
            else None
        )
        evidence_parity = legacy_evidence == graph_evidence
        error_parity = _error_signature(legacy_error) == _error_signature(graph_error)

        legacy_expected = route_ok and legacy_tools.calls == expected_tools
        graph_expected = route_ok and graph_tools.calls == expected_tools
        exact = (
            route_ok
            and tool_parity
            and result_parity
            and trace_parity
            and evidence_parity
            and error_parity
        )

        tool_parity_values.append(tool_parity)
        result_parity_values.append(result_parity)
        trace_parity_values.append(trace_parity)
        evidence_parity_values.append(evidence_parity)
        error_parity_values.append(error_parity)
        exact_values.append(exact)
        legacy_expected_values.append(legacy_expected)
        graph_expected_values.append(graph_expected)

        output_row = {
            "id": case_id,
            "question": question,
            "route": {
                "actual": route.route,
                "container_ref": route.container_ref,
                "ok": route_ok,
            },
            "planner_decisions": recorder.responses,
            "expected_tool_sequence": expected_tools,
            "legacy": {
                "tool_sequence": legacy_tools.calls,
                "results": _result_signature(legacy_result),
                "trace": _trace_signature(legacy_result),
                "evidence": legacy_evidence,
                "error": _error_signature(legacy_error),
                "expected_match": legacy_expected,
            },
            "graph": {
                "tool_sequence": graph_tools.calls,
                "results": _result_signature(graph_result),
                "trace": _trace_signature(graph_result),
                "evidence": graph_evidence,
                "error": _error_signature(graph_error),
                "expected_match": graph_expected,
            },
            "parity": {
                "tools": tool_parity,
                "results": result_parity,
                "trace": trace_parity,
                "evidence": evidence_parity,
                "error": error_parity,
                "exact": exact,
            },
        }
        parity_rows.append(output_row)

        print(
            f"[{case_id}] exact={exact} route={route_ok} "
            f"tools={tool_parity} results={result_parity} "
            f"trace={trace_parity} evidence={evidence_parity} "
            f"errors={error_parity} legacy_expected={legacy_expected} "
            f"graph_expected={graph_expected}"
        )
        if legacy_error is not None:
            print(f"  legacy error={_error_signature(legacy_error)}")
        if graph_error is not None:
            print(f"  graph error={_error_signature(graph_error)}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in parity_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = {
        "cases": len(parity_rows),
        "route_runtime_accuracy": _rate(route_ok_values),
        "tool_sequence_parity_rate": _rate(tool_parity_values),
        "result_parity_rate": _rate(result_parity_values),
        "trace_parity_rate": _rate(trace_parity_values),
        "evidence_parity_rate": _rate(evidence_parity_values),
        "error_parity_rate": _rate(error_parity_values),
        "legacy_expected_tool_accuracy": _rate(legacy_expected_values),
        "graph_expected_tool_accuracy": _rate(graph_expected_values),
        "exact_runtime_loop_parity_rate": _rate(exact_values),
        "output": str(args.output),
        "note": (
            "The LangGraph loop replays the exact planner decisions produced by the "
            "legacy loop, isolating orchestration parity from model sampling. Synthetic "
            "Docker evidence is used; no local Docker command is executed."
        ),
    }

    print("\nSummary")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
