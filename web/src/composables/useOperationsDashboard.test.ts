import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AgentRunRecord,
  AgentRunSummary,
  EvaluationComparison,
  EvaluationRun,
  EvaluationRunDetail,
} from "../lib/types";

vi.mock("../lib/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    detail: string;

    constructor(status: number, detail: string) {
      super(detail);
      this.status = status;
      this.detail = detail;
    }
  },
  compareEvaluationRuns: vi.fn(),
  getAgentRun: vi.fn(),
  getEvaluationRun: vi.fn(),
  getOperationsSummary: vi.fn(),
  listAgentRuns: vi.fn(),
  listEvaluationRuns: vi.fn(),
}));

import {
  compareEvaluationRuns,
  getAgentRun,
  getEvaluationRun,
  getOperationsSummary,
  listAgentRuns,
  listEvaluationRuns,
} from "../lib/api";
import { useOperationsDashboard } from "./useOperationsDashboard";

const summary: AgentRunSummary = {
  window_started_at: "2026-09-21T00:00:00Z",
  window_ended_at: "2026-09-22T00:00:00Z",
  total_runs: 3,
  running_runs: 1,
  succeeded_runs: 1,
  failed_runs: 1,
  success_rate: 0.5,
  failure_rate: 0.5,
  duration_p50_ms: 200,
  duration_p95_ms: 290,
  route_distribution: { docs_only: 1, runtime_tools: 1 },
  worker_distribution: { diagnosis: 2 },
  error_distribution: { RuntimeError: 1 },
};

function run(id: string): AgentRunRecord {
  return {
    id,
    conversation_id: "conversation-1",
    agent_type: "docker_support",
    status: "succeeded",
    route: "docs_only",
    use_docs: true,
    planned_workers: ["knowledge"],
    completed_workers: ["knowledge"],
    duration_ms: 120,
    error_type: null,
    error_message: null,
    started_at: "2026-09-21T01:00:00Z",
    completed_at: "2026-09-21T01:00:01Z",
  };
}

function evaluation(id: string): EvaluationRun {
  return {
    id,
    suite: "agent_router",
    dataset_name: "router.jsonl",
    dataset_version: "sha256:same",
    git_revision: "deadbeef",
    status: "succeeded",
    config_snapshot: {},
    aggregate_metrics: { exact_match_rate: 1 },
    case_count: 1,
    passed_count: 1,
    failed_count: 0,
    error_type: null,
    error_message: null,
    started_at: "2026-09-21T02:00:00Z",
    completed_at: "2026-09-21T02:00:01Z",
  };
}

function evaluationDetail(id: string): EvaluationRunDetail {
  return {
    run: evaluation(id),
    cases: [],
  };
}

const comparison: EvaluationComparison = {
  baseline_run_id: "baseline",
  candidate_run_id: "candidate",
  suite: "agent_router",
  dataset_name: "router.jsonl",
  dataset_version: "sha256:same",
  max_regression: 0.02,
  verdict: "pass",
  gate_passed: true,
  common_case_count: 1,
  baseline_only_case_keys: [],
  candidate_only_case_keys: [],
  new_failures: [],
  new_passes: [],
  unchanged_failures: [],
  metric_comparisons: [],
  behavior_changes: [],
  configuration_changes: [],
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getOperationsSummary).mockResolvedValue(summary);
  vi.mocked(listAgentRuns).mockResolvedValue([run("run-1")]);
  vi.mocked(listEvaluationRuns).mockResolvedValue([
    evaluation("eval-1"),
  ]);
  vi.mocked(getAgentRun).mockResolvedValue(run("run-1"));
  vi.mocked(getEvaluationRun).mockResolvedValue(
    evaluationDetail("eval-1"),
  );
  vi.mocked(compareEvaluationRuns).mockResolvedValue(comparison);
});

describe("operations dashboard", () => {
  it("loads summary runs and evaluations with active filters", async () => {
    const dashboard = useOperationsDashboard();
    dashboard.hours.value = 168;
    dashboard.runStatus.value = "failed";
    dashboard.evaluationSuite.value = "agent_router";

    await dashboard.loadOverview();

    expect(getOperationsSummary).toHaveBeenCalledWith(168);
    expect(listAgentRuns).toHaveBeenCalledWith({
      status: "failed",
      limit: 25,
    });
    expect(listEvaluationRuns).toHaveBeenCalledWith({
      suite: "agent_router",
      limit: 25,
    });
    expect(dashboard.summary.value).toEqual(summary);
    expect(dashboard.completedRuns.value).toBe(2);
  });

  it("ignores stale run detail responses", async () => {
    let resolveFirst:
      | ((value: AgentRunRecord) => void)
      | undefined;
    const first = new Promise<AgentRunRecord>((resolve) => {
      resolveFirst = resolve;
    });

    vi.mocked(getAgentRun)
      .mockReturnValueOnce(first)
      .mockResolvedValueOnce(run("run-2"));

    const dashboard = useOperationsDashboard();
    const firstRequest = dashboard.openRun("run-1");
    await dashboard.openRun("run-2");

    resolveFirst?.(run("run-1"));
    await firstRequest;

    expect(dashboard.activeRun.value?.id).toBe("run-2");
  });

  it("ignores stale evaluation detail responses", async () => {
    let resolveFirst:
      | ((value: EvaluationRunDetail) => void)
      | undefined;
    const first = new Promise<EvaluationRunDetail>((resolve) => {
      resolveFirst = resolve;
    });

    vi.mocked(getEvaluationRun)
      .mockReturnValueOnce(first)
      .mockResolvedValueOnce(evaluationDetail("eval-2"));

    const dashboard = useOperationsDashboard();
    const firstRequest = dashboard.openEvaluation("eval-1");
    await dashboard.openEvaluation("eval-2");

    resolveFirst?.(evaluationDetail("eval-1"));
    await firstRequest;

    expect(dashboard.activeEvaluation.value?.run.id).toBe("eval-2");
  });

  it("compares selected baseline and candidate runs", async () => {
    const dashboard = useOperationsDashboard();
    dashboard.useAsBaseline(" baseline ");
    dashboard.useAsCandidate(" candidate ");
    dashboard.maxRegression.value = 0.01;

    expect(await dashboard.compare()).toBe(true);
    expect(compareEvaluationRuns).toHaveBeenCalledWith({
      baselineId: "baseline",
      candidateId: "candidate",
      maxRegression: 0.01,
    });
    expect(dashboard.comparison.value).toEqual(comparison);
  });
});
