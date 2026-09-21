<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { useOperationsDashboard } from "../composables/useOperationsDashboard";

type OperationsTab = "overview" | "runs" | "evaluations";

const dashboard = useOperationsDashboard();
const activeTab = ref<OperationsTab>("overview");

const routeRows = computed(() =>
  distributionRows(dashboard.summary.value?.route_distribution ?? {}),
);
const workerRows = computed(() =>
  distributionRows(dashboard.summary.value?.worker_distribution ?? {}),
);
const errorRows = computed(() =>
  distributionRows(dashboard.summary.value?.error_distribution ?? {}),
);

function distributionRows(values: Record<string, number>) {
  const entries = Object.entries(values).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map(([, value]) => value));
  return entries.map(([label, value]) => ({
    label,
    value,
    width: Math.max(4, Math.round((value / max) * 100)),
  }));
}

function formatDate(value: string | null): string {
  if (!value) {
    return "—";
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatDuration(value: number | null): string {
  if (value === null) {
    return "—";
  }
  if (value < 1000) {
    return `${value} ms`;
  }
  return `${(value / 1000).toFixed(2)} s`;
}

function formatRate(value: number | null): string {
  if (value === null) {
    return "—";
  }
  return `${(value * 100).toFixed(1)}%`;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "—";
  }
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value);
}

function metricDelta(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(3)}`;
}

function selectTab(tab: OperationsTab): void {
  activeTab.value = tab;
}

onMounted(dashboard.loadOverview);
</script>

<template>
  <section class="operations-page">
    <header class="operations-hero panel">
      <div>
        <p class="section-label">Observability & evaluation</p>
        <h2>Operations</h2>
        <p>
          Inspect runtime health, recent Agent runs, persisted evaluations,
          and regression gates from one operational surface.
        </p>
      </div>

      <div class="operations-hero__actions">
        <label>
          <span>Window</span>
          <select v-model.number="dashboard.hours.value">
            <option :value="1">1 hour</option>
            <option :value="6">6 hours</option>
            <option :value="24">24 hours</option>
            <option :value="168">7 days</option>
            <option :value="720">30 days</option>
          </select>
        </label>
        <button
          class="button button--primary"
          type="button"
          :disabled="dashboard.loadingOverview.value"
          @click="dashboard.loadOverview"
        >
          {{
            dashboard.loadingOverview.value
              ? "Refreshing…"
              : "Refresh"
          }}
        </button>
      </div>
    </header>

    <div
      v-if="dashboard.errorMessage.value"
      class="alert alert--error alert--dismissible"
    >
      <span>{{ dashboard.errorMessage.value }}</span>
      <button
        type="button"
        aria-label="Dismiss error"
        @click="dashboard.errorMessage.value = ''"
      >
        ×
      </button>
    </div>

    <nav class="operations-tabs" aria-label="Operations sections">
      <button
        v-for="tab in (['overview', 'runs', 'evaluations'] as const)"
        :key="tab"
        type="button"
        :class="{ 'operations-tab--active': activeTab === tab }"
        @click="selectTab(tab)"
      >
        {{ tab }}
      </button>
    </nav>

    <template v-if="activeTab === 'overview'">
      <section class="operations-kpis">
        <article class="kpi-card panel">
          <span>Total runs</span>
          <strong>{{ dashboard.summary.value?.total_runs ?? "—" }}</strong>
          <small>
            {{ dashboard.summary.value?.running_runs ?? 0 }} running
          </small>
        </article>

        <article class="kpi-card panel">
          <span>Success rate</span>
          <strong>
            {{ formatRate(dashboard.summary.value?.success_rate ?? null) }}
          </strong>
          <small>{{ dashboard.completedRuns.value }} completed</small>
        </article>

        <article class="kpi-card panel">
          <span>P50 latency</span>
          <strong>
            {{
              formatDuration(
                dashboard.summary.value?.duration_p50_ms ?? null,
              )
            }}
          </strong>
          <small>completed runs</small>
        </article>

        <article class="kpi-card panel">
          <span>P95 latency</span>
          <strong>
            {{
              formatDuration(
                dashboard.summary.value?.duration_p95_ms ?? null,
              )
            }}
          </strong>
          <small>completed runs</small>
        </article>
      </section>

      <section class="operations-grid">
        <article class="panel distribution-panel">
          <div class="panel__header">
            <div>
              <p class="section-label">Routing</p>
              <h2>Route distribution</h2>
            </div>
          </div>
          <div v-if="routeRows.length" class="distribution-list">
            <div
              v-for="row in routeRows"
              :key="row.label"
              class="distribution-row"
            >
              <div class="distribution-row__meta">
                <span>{{ row.label }}</span>
                <strong>{{ row.value }}</strong>
              </div>
              <div class="distribution-track">
                <span :style="{ width: row.width + '%' }" />
              </div>
            </div>
          </div>
          <div v-else class="empty-state compact">No route data yet.</div>
        </article>

        <article class="panel distribution-panel">
          <div class="panel__header">
            <div>
              <p class="section-label">Workers</p>
              <h2>Worker distribution</h2>
            </div>
          </div>
          <div v-if="workerRows.length" class="distribution-list">
            <div
              v-for="row in workerRows"
              :key="row.label"
              class="distribution-row"
            >
              <div class="distribution-row__meta">
                <span>{{ row.label }}</span>
                <strong>{{ row.value }}</strong>
              </div>
              <div class="distribution-track">
                <span :style="{ width: row.width + '%' }" />
              </div>
            </div>
          </div>
          <div v-else class="empty-state compact">No worker data yet.</div>
        </article>

        <article class="panel distribution-panel">
          <div class="panel__header">
            <div>
              <p class="section-label">Failures</p>
              <h2>Error categories</h2>
            </div>
          </div>
          <div v-if="errorRows.length" class="distribution-list">
            <div
              v-for="row in errorRows"
              :key="row.label"
              class="distribution-row"
            >
              <div class="distribution-row__meta">
                <span>{{ row.label }}</span>
                <strong>{{ row.value }}</strong>
              </div>
              <div class="distribution-track">
                <span :style="{ width: row.width + '%' }" />
              </div>
            </div>
          </div>
          <div v-else class="empty-state compact">No failures recorded.</div>
        </article>
      </section>

      <section class="panel operations-recent">
        <div class="panel__header">
          <div>
            <p class="section-label">Latest activity</p>
            <h2>Recent Agent runs</h2>
          </div>
          <button
            class="button button--ghost"
            type="button"
            @click="selectTab('runs')"
          >
            Inspect runs
          </button>
        </div>

        <div v-if="dashboard.runs.value.length" class="operations-table">
          <button
            v-for="run in dashboard.runs.value.slice(0, 8)"
            :key="run.id"
            class="operations-table__row operations-table__row--button"
            type="button"
            @click="
              dashboard.openRun(run.id);
              selectTab('runs');
            "
          >
            <span>
              <strong>{{ run.route || "route pending" }}</strong>
              <small>{{ run.id.slice(0, 10) }}</small>
            </span>
            <span class="status-pill" :data-status="run.status">
              {{ run.status }}
            </span>
            <span>{{ formatDuration(run.duration_ms) }}</span>
            <span>{{ formatDate(run.started_at) }}</span>
          </button>
        </div>
        <div v-else class="empty-state compact">No runs in this window.</div>
      </section>
    </template>

    <template v-else-if="activeTab === 'runs'">
      <section class="operations-split">
        <article class="panel operations-list-panel">
          <div class="panel__header operations-filter-header">
            <div>
              <p class="section-label">Runtime telemetry</p>
              <h2>Recent runs</h2>
            </div>
            <select
              v-model="dashboard.runStatus.value"
              @change="dashboard.loadOverview"
            >
              <option value="">All statuses</option>
              <option value="running">Running</option>
              <option value="succeeded">Succeeded</option>
              <option value="failed">Failed</option>
            </select>
          </div>

          <div v-if="dashboard.runs.value.length" class="operations-table">
            <button
              v-for="run in dashboard.runs.value"
              :key="run.id"
              class="operations-table__row operations-table__row--button"
              :class="{
                'operations-table__row--active':
                  dashboard.activeRun.value?.id === run.id,
              }"
              type="button"
              @click="dashboard.openRun(run.id)"
            >
              <span>
                <strong>{{ run.route || "route pending" }}</strong>
                <small>{{ run.id }}</small>
              </span>
              <span class="status-pill" :data-status="run.status">
                {{ run.status }}
              </span>
              <span>{{ formatDuration(run.duration_ms) }}</span>
              <span>{{ formatDate(run.started_at) }}</span>
            </button>
          </div>
          <div v-else class="empty-state">No runs match this filter.</div>
        </article>

        <aside class="panel operations-detail-panel">
          <div class="panel__header">
            <div>
              <p class="section-label">Run detail</p>
              <h2>Execution trace</h2>
            </div>
          </div>

          <div
            v-if="dashboard.loadingRun.value"
            class="empty-state compact"
          >
            Loading run…
          </div>

          <div
            v-else-if="!dashboard.activeRun.value"
            class="empty-state"
          >
            Select a run to inspect its route, workers, duration, and error.
          </div>

          <template v-else>
            <dl class="operations-facts">
              <div>
                <dt>Status</dt>
                <dd>
                  <span
                    class="status-pill"
                    :data-status="dashboard.activeRun.value.status"
                  >
                    {{ dashboard.activeRun.value.status }}
                  </span>
                </dd>
              </div>
              <div>
                <dt>Run ID</dt>
                <dd><code>{{ dashboard.activeRun.value.id }}</code></dd>
              </div>
              <div>
                <dt>Conversation</dt>
                <dd>
                  <code>
                    {{ dashboard.activeRun.value.conversation_id }}
                  </code>
                </dd>
              </div>
              <div>
                <dt>Route</dt>
                <dd>{{ dashboard.activeRun.value.route || "—" }}</dd>
              </div>
              <div>
                <dt>Duration</dt>
                <dd>
                  {{ formatDuration(dashboard.activeRun.value.duration_ms) }}
                </dd>
              </div>
              <div>
                <dt>Started</dt>
                <dd>{{ formatDate(dashboard.activeRun.value.started_at) }}</dd>
              </div>
            </dl>

            <section class="operations-detail-section">
              <h3>Workers</h3>
              <div class="chip-row">
                <span
                  v-for="worker in dashboard.activeRun.value.completed_workers"
                  :key="worker"
                  class="chip"
                >
                  {{ worker }}
                </span>
                <span
                  v-if="
                    dashboard.activeRun.value.completed_workers.length === 0
                  "
                  class="field-hint"
                >
                  No completed workers.
                </span>
              </div>
            </section>

            <section
              v-if="dashboard.activeRun.value.error_type"
              class="operations-detail-section operations-error-detail"
            >
              <h3>{{ dashboard.activeRun.value.error_type }}</h3>
              <p>{{ dashboard.activeRun.value.error_message || "No detail." }}</p>
            </section>
          </template>
        </aside>
      </section>
    </template>

    <template v-else>
      <section class="operations-split operations-split--evaluations">
        <article class="panel operations-list-panel">
          <div class="panel__header operations-filter-header">
            <div>
              <p class="section-label">Quality history</p>
              <h2>Evaluation runs</h2>
            </div>
            <input
              v-model="dashboard.evaluationSuite.value"
              placeholder="Filter suite"
              @keydown.enter="dashboard.loadOverview"
            />
          </div>

          <div
            v-if="dashboard.evaluations.value.length"
            class="evaluation-list"
          >
            <article
              v-for="evaluation in dashboard.evaluations.value"
              :key="evaluation.id"
              class="evaluation-card"
              :class="{
                'evaluation-card--active':
                  dashboard.activeEvaluation.value?.run.id === evaluation.id,
              }"
            >
              <button
                class="evaluation-card__main"
                type="button"
                @click="dashboard.openEvaluation(evaluation.id)"
              >
                <span>
                  <strong>{{ evaluation.suite }}</strong>
                  <small>{{ evaluation.dataset_name }}</small>
                </span>
                <span class="status-pill" :data-status="evaluation.status">
                  {{ evaluation.status }}
                </span>
                <span>
                  {{ evaluation.passed_count }}/{{ evaluation.case_count }}
                  passed
                </span>
                <span>{{ formatDate(evaluation.started_at) }}</span>
              </button>

              <div class="evaluation-card__actions">
                <button
                  type="button"
                  @click="dashboard.useAsBaseline(evaluation.id)"
                >
                  Baseline
                </button>
                <button
                  type="button"
                  @click="dashboard.useAsCandidate(evaluation.id)"
                >
                  Candidate
                </button>
              </div>
            </article>
          </div>
          <div v-else class="empty-state">No persisted evaluations yet.</div>
        </article>

        <aside class="panel operations-detail-panel">
          <div class="panel__header">
            <div>
              <p class="section-label">Evaluation detail</p>
              <h2>Cases & metrics</h2>
            </div>
          </div>

          <div
            v-if="dashboard.loadingEvaluation.value"
            class="empty-state compact"
          >
            Loading evaluation…
          </div>

          <div
            v-else-if="!dashboard.activeEvaluation.value"
            class="empty-state"
          >
            Select an evaluation run to inspect persisted cases.
          </div>

          <template v-else>
            <dl class="operations-facts">
              <div>
                <dt>Suite</dt>
                <dd>{{ dashboard.activeEvaluation.value.run.suite }}</dd>
              </div>
              <div>
                <dt>Dataset</dt>
                <dd>
                  {{ dashboard.activeEvaluation.value.run.dataset_name }}
                </dd>
              </div>
              <div>
                <dt>Revision</dt>
                <dd>
                  <code>
                    {{
                      dashboard.activeEvaluation.value.run.git_revision ||
                      "—"
                    }}
                  </code>
                </dd>
              </div>
              <div>
                <dt>Cases</dt>
                <dd>
                  {{ dashboard.activeEvaluation.value.run.case_count }}
                </dd>
              </div>
            </dl>

            <section class="operations-detail-section">
              <h3>Aggregate metrics</h3>
              <pre class="operations-json">{{
                JSON.stringify(
                  dashboard.activeEvaluation.value.run.aggregate_metrics,
                  null,
                  2,
                )
              }}</pre>
            </section>

            <section class="operations-detail-section">
              <h3>Cases</h3>
              <div class="evaluation-case-list">
                <div
                  v-for="evaluationCase in dashboard.activeEvaluation.value.cases"
                  :key="evaluationCase.id"
                  class="evaluation-case"
                >
                  <span>{{ evaluationCase.case_key }}</span>
                  <span
                    class="status-pill"
                    :data-status="evaluationCase.status"
                  >
                    {{ evaluationCase.status }}
                  </span>
                </div>
              </div>
            </section>
          </template>
        </aside>
      </section>

      <section class="panel comparison-panel">
        <div class="panel__header">
          <div>
            <p class="section-label">Release quality gate</p>
            <h2>Baseline vs candidate</h2>
          </div>
        </div>

        <div class="comparison-form">
          <label>
            <span>Baseline run</span>
            <input v-model="dashboard.baselineId.value" />
          </label>
          <label>
            <span>Candidate run</span>
            <input v-model="dashboard.candidateId.value" />
          </label>
          <label>
            <span>Max regression</span>
            <input
              v-model.number="dashboard.maxRegression.value"
              type="number"
              min="0"
              step="0.01"
            />
          </label>
          <button
            class="button button--primary"
            type="button"
            :disabled="
              dashboard.comparing.value ||
              !dashboard.baselineId.value ||
              !dashboard.candidateId.value
            "
            @click="dashboard.compare"
          >
            {{ dashboard.comparing.value ? "Comparing…" : "Compare" }}
          </button>
        </div>

        <div
          v-if="dashboard.comparison.value"
          class="comparison-result"
        >
          <div class="comparison-verdict">
            <div>
              <p class="section-label">Verdict</p>
              <strong
                class="verdict-badge"
                :data-verdict="dashboard.comparison.value.verdict"
              >
                {{ dashboard.comparison.value.verdict }}
              </strong>
            </div>
            <div>
              <span>Common cases</span>
              <strong>
                {{ dashboard.comparison.value.common_case_count }}
              </strong>
            </div>
            <div>
              <span>New failures</span>
              <strong>
                {{ dashboard.comparison.value.new_failures.length }}
              </strong>
            </div>
            <div>
              <span>New passes</span>
              <strong>
                {{ dashboard.comparison.value.new_passes.length }}
              </strong>
            </div>
          </div>

          <section class="comparison-section">
            <h3>Metric deltas</h3>
            <div
              v-if="dashboard.comparison.value.metric_comparisons.length"
              class="comparison-metrics"
            >
              <div
                v-for="metric in dashboard.comparison.value.metric_comparisons"
                :key="metric.path"
                class="comparison-metric"
                :class="{
                  'comparison-metric--regression': metric.regression,
                  'comparison-metric--improvement': metric.improvement,
                }"
              >
                <span>{{ metric.path }}</span>
                <strong>{{ metricDelta(metric.quality_delta) }}</strong>
                <small>
                  {{ metric.baseline_value }} → {{ metric.candidate_value }}
                </small>
              </div>
            </div>
            <p v-else class="field-hint">
              No common numeric quality metrics were found.
            </p>
          </section>

          <section class="comparison-section comparison-columns">
            <div>
              <h3>New failures</h3>
              <code
                v-for="caseKey in dashboard.comparison.value.new_failures"
                :key="caseKey"
              >
                {{ caseKey }}
              </code>
              <span
                v-if="!dashboard.comparison.value.new_failures.length"
                class="field-hint"
              >
                None
              </span>
            </div>

            <div>
              <h3>Behavior changes</h3>
              <div
                v-for="change in dashboard.comparison.value.behavior_changes"
                :key="`${change.case_key}-${change.field}`"
                class="comparison-change"
              >
                <strong>{{ change.case_key }} · {{ change.field }}</strong>
                <small>
                  {{ formatValue(change.baseline_value) }}
                  →
                  {{ formatValue(change.candidate_value) }}
                </small>
              </div>
              <span
                v-if="!dashboard.comparison.value.behavior_changes.length"
                class="field-hint"
              >
                None
              </span>
            </div>

            <div>
              <h3>Configuration changes</h3>
              <div
                v-for="change in dashboard.comparison.value.configuration_changes"
                :key="change.path"
                class="comparison-change"
              >
                <strong>{{ change.path }}</strong>
                <small>
                  {{ formatValue(change.baseline_value) }}
                  →
                  {{ formatValue(change.candidate_value) }}
                </small>
              </div>
              <span
                v-if="!dashboard.comparison.value.configuration_changes.length"
                class="field-hint"
              >
                None
              </span>
            </div>
          </section>
        </div>
      </section>
    </template>
  </section>
</template>
