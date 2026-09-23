import { computed, ref } from "vue";

import {
  ApiError,
  compareEvaluationRuns,
  getAgentRun,
  getEvaluationRun,
  getOperationsSummary,
  listAgentRuns,
  listAgents,
  listEvaluationRuns,
} from "../lib/api";
import type {
  AgentDescriptor,
  AgentRunRecord,
  AgentRunStatus,
  AgentRunSummary,
  EvaluationComparison,
  EvaluationRun,
  EvaluationRunDetail,
} from "../lib/types";

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    return error.detail;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Something went wrong.";
}

export function useOperationsDashboard() {
  const agents = ref<AgentDescriptor[]>([]);
  const summary = ref<AgentRunSummary | null>(null);
  const runs = ref<AgentRunRecord[]>([]);
  const evaluations = ref<EvaluationRun[]>([]);
  const activeRun = ref<AgentRunRecord | null>(null);
  const activeEvaluation = ref<EvaluationRunDetail | null>(null);
  const comparison = ref<EvaluationComparison | null>(null);

  const hours = ref(24);
  const agentType = ref("");
  const runStatus = ref<AgentRunStatus | "">("");
  const evaluationSuite = ref("");
  const baselineId = ref("");
  const candidateId = ref("");
  const maxRegression = ref(0.02);

  const loadingOverview = ref(false);
  const loadingRun = ref(false);
  const loadingEvaluation = ref(false);
  const comparing = ref(false);
  const errorMessage = ref("");

  let runRequestVersion = 0;
  let evaluationRequestVersion = 0;

  const completedRuns = computed(
    () =>
      (summary.value?.succeeded_runs ?? 0) +
      (summary.value?.failed_runs ?? 0),
  );

  function agentDisplayName(value: string | null): string {
    if (!value) {
      return "Platform-wide";
    }
    return (
      agents.value.find((agent) => agent.agent_type === value)
        ?.display_name ?? value
    );
  }

  async function initialize(): Promise<void> {
    loadingOverview.value = true;
    errorMessage.value = "";
    try {
      agents.value = await listAgents();
    } catch (error) {
      errorMessage.value = errorText(error);
    } finally {
      loadingOverview.value = false;
    }
    await loadOverview();
  }

  async function loadOverview(): Promise<void> {
    loadingOverview.value = true;
    errorMessage.value = "";

    try {
      const [nextSummary, nextRuns, nextEvaluations] =
        await Promise.all([
          getOperationsSummary(
            hours.value,
            agentType.value || undefined,
          ),
          listAgentRuns({
            agentType: agentType.value || undefined,
            status: runStatus.value || undefined,
            limit: 25,
          }),
          listEvaluationRuns({
            suite: evaluationSuite.value || undefined,
            agentType: agentType.value || undefined,
            limit: 25,
          }),
        ]);

      summary.value = nextSummary;
      runs.value = nextRuns;
      evaluations.value = nextEvaluations;

      if (
        activeRun.value &&
        !nextRuns.some((item) => item.id === activeRun.value?.id)
      ) {
        activeRun.value = null;
      }
      if (
        activeEvaluation.value &&
        !nextEvaluations.some(
          (item) => item.id === activeEvaluation.value?.run.id,
        )
      ) {
        activeEvaluation.value = null;
      }
    } catch (error) {
      errorMessage.value = errorText(error);
    } finally {
      loadingOverview.value = false;
    }
  }

  async function openRun(runId: string): Promise<void> {
    const version = ++runRequestVersion;
    loadingRun.value = true;
    errorMessage.value = "";

    try {
      const next = await getAgentRun(runId);
      if (version === runRequestVersion) {
        activeRun.value = next;
      }
    } catch (error) {
      if (version === runRequestVersion) {
        errorMessage.value = errorText(error);
      }
    } finally {
      if (version === runRequestVersion) {
        loadingRun.value = false;
      }
    }
  }

  async function openEvaluation(runId: string): Promise<void> {
    const version = ++evaluationRequestVersion;
    loadingEvaluation.value = true;
    errorMessage.value = "";

    try {
      const next = await getEvaluationRun(runId);
      if (version === evaluationRequestVersion) {
        activeEvaluation.value = next;
      }
    } catch (error) {
      if (version === evaluationRequestVersion) {
        errorMessage.value = errorText(error);
      }
    } finally {
      if (version === evaluationRequestVersion) {
        loadingEvaluation.value = false;
      }
    }
  }

  function useAsBaseline(runId: string): void {
    baselineId.value = runId;
    comparison.value = null;
  }

  function useAsCandidate(runId: string): void {
    candidateId.value = runId;
    comparison.value = null;
  }

  async function compare(): Promise<boolean> {
    if (
      !baselineId.value.trim() ||
      !candidateId.value.trim() ||
      comparing.value
    ) {
      return false;
    }

    comparing.value = true;
    errorMessage.value = "";

    try {
      comparison.value = await compareEvaluationRuns({
        baselineId: baselineId.value.trim(),
        candidateId: candidateId.value.trim(),
        maxRegression: maxRegression.value,
      });
      return true;
    } catch (error) {
      errorMessage.value = errorText(error);
      comparison.value = null;
      return false;
    } finally {
      comparing.value = false;
    }
  }

  return {
    agents,
    summary,
    runs,
    evaluations,
    activeRun,
    activeEvaluation,
    comparison,
    hours,
    agentType,
    runStatus,
    evaluationSuite,
    baselineId,
    candidateId,
    maxRegression,
    loadingOverview,
    loadingRun,
    loadingEvaluation,
    comparing,
    errorMessage,
    completedRuns,
    agentDisplayName,
    initialize,
    loadOverview,
    openRun,
    openEvaluation,
    useAsBaseline,
    useAsCandidate,
    compare,
  };
}
