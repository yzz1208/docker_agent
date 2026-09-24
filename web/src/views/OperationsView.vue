<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { useOperationsDashboard } from "../composables/useOperationsDashboard";

type OperationsTab = "overview" | "runs" | "evaluations";

const dashboard = useOperationsDashboard();
const activeTab = ref<OperationsTab>("overview");
const tabs: OperationsTab[] = ["overview", "runs", "evaluations"];
let refreshTimer: number | null = null;

const activeRun = computed(() => dashboard.activeRun.value);
const activeEvaluation = computed(
  () => dashboard.activeEvaluation.value,
);
const comparison = computed(() => dashboard.comparison.value);

const agentRows = computed(() =>
  distributionRows(dashboard.summary.value?.agent_distribution ?? {}),
);
const routeRows = computed(() =>
  distributionRows(dashboard.summary.value?.route_distribution ?? {}),
);
const workerRows = computed(() =>
  distributionRows(dashboard.summary.value?.worker_distribution ?? {}),
);
const errorRows = computed(() =>
  distributionRows(dashboard.summary.value?.error_distribution ?? {}),
);
const slowStageRows = computed(() =>
  [...(dashboard.performance.value?.stages ?? [])]
    .filter((item) => item.count > 0)
    .sort((a, b) => b.average_ms - a.average_ms)
    .slice(0, 6),
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
  return new Intl.DateTimeFormat("zh-CN", {
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

function stageLabel(value: string): string {
  const labels: Record<string, string> = {
    orchestration_decision: "智能编排判断",
    decision: "专家路由判断",
    rag_database: "知识库检查",
    embedding: "问题向量化",
    dense_retrieval: "语义检索",
    keyword_retrieval: "关键词检索",
    fusion: "检索融合",
    rerank: "文档重排",
    context_build: "证据整理",
    runtime: "运行时诊断",
    answer: "回答生成",
    synthesis: "多专家综合",
    embedding_model_warmup: "Embedding 预热",
    reranker_model_warmup: "Reranker 预热",
  };
  return labels[value] ?? value;
}

function statusLabel(value: string): string {
  const labels: Record<string, string> = {
    running: "执行中",
    succeeded: "成功",
    failed: "失败",
    passed: "通过",
    error: "错误",
    regression: "存在回归",
    incomplete: "不完整",
  };
  return labels[value] ?? value;
}

function routeLabel(value: string): string {
  const labels: Record<string, string> = {
    clarify: "补充信息",
    docs_only: "文档解答",
    runtime_only: "运行时检查",
    runtime_tools: "运行时诊断",
    triage: "故障分诊",
    auto_direct: "专家直达",
    auto_direct_clarify: "专家补充信息",
    auto_delegate_clarify: "转交后补充信息",
    auto_synthesis: "多专家综合",
    auto_approval_pending: "等待审批",
    auto_approval_denied: "审批拒绝",
  };
  return labels[value] ?? value;
}

function tabLabel(value: OperationsTab): string {
  const labels: Record<OperationsTab, string> = {
    overview: "概览",
    runs: "执行记录",
    evaluations: "质量评测",
  };
  return labels[value];
}

function workerLabel(value: string): string {
  const labels: Record<string, string> = {
    diagnosis: "诊断",
    knowledge: "知识检索",
    runtime: "运行时检查",
    synthesis: "结果综合",
  };
  return labels[value] ?? value;
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

async function openRunFromOverview(runId: string): Promise<void> {
  await dashboard.openRun(runId);
  selectTab("runs");
}

onMounted(async () => {
  await dashboard.initialize();
  refreshTimer = window.setInterval(() => {
    if (!dashboard.loadingOverview.value) {
      void dashboard.loadOverview();
    }
  }, 15_000);
});

onBeforeUnmount(() => {
  if (refreshTimer !== null) {
    window.clearInterval(refreshTimer);
  }
});
</script>

<template>
  <section class="operations-page">
    <header class="operations-hero panel">
      <div>
        <p class="section-label">运行观测与评测</p>
        <h2>运行观测</h2>
        <p>
          集中查看运行状态、最近执行、持久化评测和回归门禁，
          快速定位系统性能与质量问题。
        </p>
      </div>

      <div class="operations-hero__actions">
        <span class="operations-auto-refresh">每 15 秒自动刷新</span>
        <label>
          <span>专家</span>
          <select
            v-model="dashboard.agentType.value"
            @change="dashboard.loadOverview"
          >
            <option value="">全部专家</option>
            <option
              v-for="agent in dashboard.agents.value"
              :key="agent.agent_type"
              :value="agent.agent_type"
            >
              {{ dashboard.agentDisplayName(agent.agent_type) }}
            </option>
          </select>
        </label>
        <label>
          <span>时间范围</span>
          <select v-model.number="dashboard.hours.value">
            <option :value="1">1 小时</option>
            <option :value="6">6 小时</option>
            <option :value="24">24 小时</option>
            <option :value="168">7 天</option>
            <option :value="720">30 天</option>
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
              ? "刷新中…"
              : "刷新"
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
        aria-label="关闭错误提示"
        @click="dashboard.errorMessage.value = ''"
      >
        ×
      </button>
    </div>

    <nav class="operations-tabs" aria-label="运行观测栏目">
      <button
        v-for="tab in tabs"
        :key="tab"
        type="button"
        :class="{ 'operations-tab--active': activeTab === tab }"
        @click="selectTab(tab)"
      >
        {{ tabLabel(tab) }}
      </button>
    </nav>

    <template v-if="activeTab === 'overview'">
      <section class="operations-kpis">
        <article class="kpi-card panel">
          <span>执行总数</span>
          <strong>{{ dashboard.summary.value?.total_runs ?? "—" }}</strong>
          <small>
            {{ dashboard.summary.value?.running_runs ?? 0 }} 执行中
          </small>
        </article>

        <article class="kpi-card panel">
          <span>成功率</span>
          <strong>
            {{ formatRate(dashboard.summary.value?.success_rate ?? null) }}
          </strong>
          <small>{{ dashboard.completedRuns.value }} 已完成</small>
        </article>

        <article class="kpi-card panel">
          <span>P50 延迟</span>
          <strong>
            {{
              formatDuration(
                dashboard.summary.value?.duration_p50_ms ?? null,
              )
            }}
          </strong>
          <small>已完成执行</small>
        </article>

        <article class="kpi-card panel">
          <span>P95 延迟</span>
          <strong>
            {{
              formatDuration(
                dashboard.summary.value?.duration_p95_ms ?? null,
              )
            }}
          </strong>
          <small>已完成执行</small>
        </article>

        <article class="kpi-card panel">
          <span>首字延迟</span>
          <strong>
            {{
              formatDuration(
                dashboard.performance.value?.ttft_average_ms ?? null,
              )
            }}
          </strong>
          <small>
            {{ dashboard.performance.value?.ttft_count ?? 0 }} 次流式回答
          </small>
        </article>

        <article class="kpi-card panel">
          <span>TTFT P95 上界</span>
          <strong>
            {{
              formatDuration(
                dashboard.performance.value?.ttft_p95_upper_ms ?? null,
              )
            }}
          </strong>
          <small>Prometheus 直方图估算</small>
        </article>
      </section>

      <section class="operations-grid">
        <article class="panel distribution-panel">
          <div class="panel__header">
            <div>
              <p class="section-label">专家分布</p>
              <h2>专家执行分布</h2>
            </div>
          </div>
          <div v-if="agentRows.length" class="distribution-list">
            <div
              v-for="row in agentRows"
              :key="row.label"
              class="distribution-row"
            >
              <div class="distribution-row__meta">
                <span>{{ dashboard.agentDisplayName(row.label) }}</span>
                <strong>{{ row.value }}</strong>
              </div>
              <div class="distribution-track">
                <span :style="{ width: row.width + '%' }" />
              </div>
            </div>
          </div>
          <div v-else class="empty-state compact">暂无专家执行数据。</div>
        </article>

        <article class="panel distribution-panel">
          <div class="panel__header">
            <div>
              <p class="section-label">路由</p>
              <h2>路由分布</h2>
            </div>
          </div>
          <div v-if="routeRows.length" class="distribution-list">
            <div
              v-for="row in routeRows"
              :key="row.label"
              class="distribution-row"
            >
              <div class="distribution-row__meta">
                <span>{{ routeLabel(row.label) }}</span>
                <strong>{{ row.value }}</strong>
              </div>
              <div class="distribution-track">
                <span :style="{ width: row.width + '%' }" />
              </div>
            </div>
          </div>
          <div v-else class="empty-state compact">暂无路由数据。</div>
        </article>

        <article class="panel distribution-panel">
          <div class="panel__header">
            <div>
              <p class="section-label">工作单元</p>
              <h2>工作单元分布</h2>
            </div>
          </div>
          <div v-if="workerRows.length" class="distribution-list">
            <div
              v-for="row in workerRows"
              :key="row.label"
              class="distribution-row"
            >
              <div class="distribution-row__meta">
                <span>{{ workerLabel(row.label) }}</span>
                <strong>{{ row.value }}</strong>
              </div>
              <div class="distribution-track">
                <span :style="{ width: row.width + '%' }" />
              </div>
            </div>
          </div>
          <div v-else class="empty-state compact">暂无工作单元数据。</div>
        </article>

        <article class="panel distribution-panel">
          <div class="panel__header">
            <div>
              <p class="section-label">失败</p>
              <h2>错误分类</h2>
            </div>
          </div>
          <div v-if="errorRows.length" class="distribution-list">
            <div
              v-for="row in errorRows"
              :key="row.label"
              class="distribution-row"
            >
              <div class="distribution-row__meta">
                <span>{{ routeLabel(row.label) }}</span>
                <strong>{{ row.value }}</strong>
              </div>
              <div class="distribution-track">
                <span :style="{ width: row.width + '%' }" />
              </div>
            </div>
          </div>
          <div v-else class="empty-state compact">当前没有失败记录。</div>
        </article>
      </section>

      <section class="panel operations-recent">
        <div class="panel__header">
          <div>
            <p class="section-label">实时性能</p>
            <h2>最慢执行阶段</h2>
          </div>
          <span class="field-hint">进程启动后的内存指标</span>
        </div>

        <div v-if="slowStageRows.length" class="operations-table">
          <div
            v-for="stage in slowStageRows"
            :key="stage.stage"
            class="operations-table__row"
          >
            <span>
              <strong>{{ stageLabel(stage.stage) }}</strong>
              <small>{{ stage.count }} 次采样</small>
            </span>
            <span>平均 {{ formatDuration(stage.average_ms) }}</span>
            <span>P50 ≤ {{ formatDuration(stage.p50_upper_ms) }}</span>
            <span>P95 ≤ {{ formatDuration(stage.p95_upper_ms) }}</span>
          </div>
        </div>
        <div v-else class="empty-state compact">
          暂无阶段耗时数据。执行一次智能编排后即可查看。
        </div>
      </section>

      <section class="panel operations-recent">
        <div class="panel__header">
          <div>
            <p class="section-label">最近活动</p>
            <h2>最近执行</h2>
          </div>
          <button
            class="button button--ghost"
            type="button"
            @click="selectTab('runs')"
          >
            查看执行
          </button>
        </div>

        <div v-if="dashboard.runs.value.length" class="operations-table">
          <button
            v-for="run in dashboard.runs.value.slice(0, 8)"
            :key="run.id"
            class="operations-table__row operations-table__row--button"
            type="button"
            @click="openRunFromOverview(run.id)"
          >
            <span>
              <strong>{{ run.route ? routeLabel(run.route) : "路由待定" }}</strong>
              <small>
                {{ dashboard.agentDisplayName(run.agent_type) }}
                · {{ run.id.slice(0, 10) }}
              </small>
            </span>
            <span class="status-pill" :data-status="run.status">
              {{ statusLabel(run.status) }}
            </span>
            <span>{{ formatDuration(run.duration_ms) }}</span>
            <span>{{ formatDate(run.started_at) }}</span>
          </button>
        </div>
        <div v-else class="empty-state compact">当前时间范围内暂无执行记录。</div>
      </section>
    </template>

    <template v-else-if="activeTab === 'runs'">
      <section class="operations-split">
        <article class="panel operations-list-panel">
          <div class="panel__header operations-filter-header">
            <div>
              <p class="section-label">运行遥测</p>
              <h2>最近执行</h2>
            </div>
            <select
              v-model="dashboard.runStatus.value"
              @change="dashboard.loadOverview"
            >
              <option value="">全部状态</option>
              <option value="running">执行中</option>
              <option value="succeeded">成功</option>
              <option value="failed">失败</option>
            </select>
          </div>

          <div v-if="dashboard.runs.value.length" class="operations-table">
            <button
              v-for="run in dashboard.runs.value"
              :key="run.id"
              class="operations-table__row operations-table__row--button"
              :class="{
                'operations-table__row--active':
                  activeRun?.id === run.id,
              }"
              type="button"
              @click="dashboard.openRun(run.id)"
            >
              <span>
                <strong>{{ run.route ? routeLabel(run.route) : "路由待定" }}</strong>
                <small>
                  {{ dashboard.agentDisplayName(run.agent_type) }}
                  · {{ run.id }}
                </small>
              </span>
              <span class="status-pill" :data-status="run.status">
                {{ statusLabel(run.status) }}
              </span>
              <span>{{ formatDuration(run.duration_ms) }}</span>
              <span>{{ formatDate(run.started_at) }}</span>
            </button>
          </div>
          <div v-else class="empty-state">没有符合当前筛选条件的执行。</div>
        </article>

        <aside class="panel operations-detail-panel">
          <div class="panel__header">
            <div>
              <p class="section-label">执行详情</p>
              <h2>执行轨迹</h2>
            </div>
          </div>

          <div
            v-if="dashboard.loadingRun.value"
            class="empty-state compact"
          >
            正在加载执行详情…
          </div>

          <div
            v-else-if="!activeRun"
            class="empty-state"
          >
            选择一条执行记录，查看路由、工作单元、耗时和错误信息。
          </div>

          <template v-else>
            <dl class="operations-facts">
              <div>
                <dt>专家</dt>
                <dd>{{ dashboard.agentDisplayName(activeRun.agent_type) }}</dd>
              </div>
              <div>
                <dt>状态</dt>
                <dd>
                  <span
                    class="status-pill"
                    :data-status="activeRun.status"
                  >
                    {{ statusLabel(activeRun.status) }}
                  </span>
                </dd>
              </div>
              <div>
                <dt>执行 ID</dt>
                <dd><code>{{ activeRun.id }}</code></dd>
              </div>
              <div>
                <dt>对话</dt>
                <dd>
                  <code>
                    {{ activeRun.conversation_id }}
                  </code>
                </dd>
              </div>
              <div>
                <dt>路由</dt>
                <dd>{{ activeRun.route ? routeLabel(activeRun.route) : "—" }}</dd>
              </div>
              <div>
                <dt>耗时</dt>
                <dd>
                  {{ formatDuration(activeRun.duration_ms) }}
                </dd>
              </div>
              <div>
                <dt>开始时间</dt>
                <dd>{{ formatDate(activeRun.started_at) }}</dd>
              </div>
            </dl>

            <section class="operations-detail-section">
              <h3>工作单元</h3>
              <div class="chip-row">
                <span
                  v-for="worker in activeRun.completed_workers"
                  :key="worker"
                  class="chip"
                >
                  {{ worker }}
                </span>
                <span
                  v-if="
                    activeRun.completed_workers.length === 0
                  "
                  class="field-hint"
                >
                  暂无已完成工作单元。
                </span>
              </div>
            </section>

            <section
              v-if="activeRun.error_type"
              class="operations-detail-section operations-error-detail"
            >
              <h3>{{ activeRun.error_type }}</h3>
              <p>{{ activeRun.error_message || "暂无详细信息。" }}</p>
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
              <p class="section-label">质量历史</p>
              <h2>评测记录</h2>
            </div>
            <input
              v-model="dashboard.evaluationSuite.value"
              placeholder="筛选评测套件"
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
                  activeEvaluation?.run.id === evaluation.id,
              }"
            >
              <button
                class="evaluation-card__main"
                type="button"
                @click="dashboard.openEvaluation(evaluation.id)"
              >
                <span>
                  <strong>{{ evaluation.suite }}</strong>
                  <small>
                    {{ dashboard.agentDisplayName(evaluation.agent_type) }}
                    · {{ evaluation.dataset_name }}
                  </small>
                </span>
                <span class="status-pill" :data-status="evaluation.status">
                  {{ statusLabel(evaluation.status) }}
                </span>
                <span>
                  {{ evaluation.passed_count }}/{{ evaluation.case_count }}
                  通过
                </span>
                <span>{{ formatDate(evaluation.started_at) }}</span>
              </button>

              <div class="evaluation-card__actions">
                <button
                  type="button"
                  @click="dashboard.useAsBaseline(evaluation.id)"
                >
                  设为基线
                </button>
                <button
                  type="button"
                  @click="dashboard.useAsCandidate(evaluation.id)"
                >
                  设为候选
                </button>
              </div>
            </article>
          </div>
          <div v-else class="empty-state">暂无持久化评测记录。</div>
        </article>

        <aside class="panel operations-detail-panel">
          <div class="panel__header">
            <div>
              <p class="section-label">评测详情</p>
              <h2>用例与指标</h2>
            </div>
          </div>

          <div
            v-if="dashboard.loadingEvaluation.value"
            class="empty-state compact"
          >
            正在加载评测详情…
          </div>

          <div
            v-else-if="!activeEvaluation"
            class="empty-state"
          >
            选择一条评测记录查看持久化用例。
          </div>

          <template v-else>
            <dl class="operations-facts">
              <div>
                <dt>专家</dt>
                <dd>
                  {{ dashboard.agentDisplayName(activeEvaluation.run.agent_type) }}
                </dd>
              </div>
              <div>
                <dt>评测套件</dt>
                <dd>{{ activeEvaluation.run.suite }}</dd>
              </div>
              <div>
                <dt>数据集</dt>
                <dd>
                  {{ activeEvaluation.run.dataset_name }}
                </dd>
              </div>
              <div>
                <dt>代码版本</dt>
                <dd>
                  <code>
                    {{
                      activeEvaluation.run.git_revision ||
                      "—"
                    }}
                  </code>
                </dd>
              </div>
              <div>
                <dt>用例</dt>
                <dd>
                  {{ activeEvaluation.run.case_count }}
                </dd>
              </div>
            </dl>

            <section class="operations-detail-section">
              <h3>汇总指标</h3>
              <pre class="operations-json">{{
                JSON.stringify(
                  activeEvaluation.run.aggregate_metrics,
                  null,
                  2,
                )
              }}</pre>
            </section>

            <section class="operations-detail-section">
              <h3>用例</h3>
              <div class="evaluation-case-list">
                <div
                  v-for="evaluationCase in activeEvaluation.cases"
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
            <p class="section-label">发布质量门禁</p>
            <h2>基线与候选版本对比</h2>
          </div>
        </div>

        <div class="comparison-form">
          <label>
            <span>基线评测</span>
            <input v-model="dashboard.baselineId.value" />
          </label>
          <label>
            <span>候选评测</span>
            <input v-model="dashboard.candidateId.value" />
          </label>
          <label>
            <span>最大允许回归</span>
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
            {{ dashboard.comparing.value ? "对比中…" : "开始对比" }}
          </button>
        </div>

        <div
          v-if="comparison"
          class="comparison-result"
        >
          <div class="comparison-verdict">
            <div>
              <p class="section-label">结论</p>
              <strong
                class="verdict-badge"
                :data-verdict="comparison.verdict"
              >
                {{ comparison.verdict === "pass" ? "通过" : comparison.verdict === "regression" ? "存在回归" : "不完整" }}
              </strong>
            </div>
            <div>
              <span>专家</span>
              <strong>
                {{ dashboard.agentDisplayName(comparison.agent_type) }}
              </strong>
            </div>
            <div>
              <span>共同用例</span>
              <strong>
                {{ comparison.common_case_count }}
              </strong>
            </div>
            <div>
              <span>新增失败</span>
              <strong>
                {{ comparison.new_failures.length }}
              </strong>
            </div>
            <div>
              <span>新增通过</span>
              <strong>
                {{ comparison.new_passes.length }}
              </strong>
            </div>
          </div>

          <section class="comparison-section">
            <h3>指标变化</h3>
            <div
              v-if="comparison.metric_comparisons.length"
              class="comparison-metrics"
            >
              <div
                v-for="metric in comparison.metric_comparisons"
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
              没有可对比的共同数值指标。
            </p>
          </section>

          <section class="comparison-section comparison-columns">
            <div>
              <h3>新增失败</h3>
              <code
                v-for="caseKey in comparison.new_failures"
                :key="caseKey"
              >
                {{ caseKey }}
              </code>
              <span
                v-if="!comparison.new_failures.length"
                class="field-hint"
              >
                暂无
              </span>
            </div>

            <div>
              <h3>行为变化</h3>
              <div
                v-for="change in comparison.behavior_changes"
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
                v-if="!comparison.behavior_changes.length"
                class="field-hint"
              >
                暂无
              </span>
            </div>

            <div>
              <h3>配置变化</h3>
              <div
                v-for="change in comparison.configuration_changes"
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
                v-if="!comparison.configuration_changes.length"
                class="field-hint"
              >
                暂无
              </span>
            </div>
          </section>
        </div>
      </section>
    </template>
  </section>
</template>
