<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { listAgents } from "../lib/api";
import {
  type EditableSettingField,
  type SettingGroupKey,
  useAgentSettings,
} from "../composables/useAgentSettings";
import type {
  AgentDescriptor,
  EffectiveConfigurationField,
} from "../lib/types";

const settings = useAgentSettings();
const agents = ref<AgentDescriptor[]>([]);
const catalogLoading = ref(false);
const catalogError = ref("");

const editableGroups = computed(() =>
  (settings.descriptor.value?.configuration_schema ?? [])
    .filter((group) => group.key in settings.fields.value)
    .map((group) => ({
      key: group.key as SettingGroupKey,
      label: group.label,
      fields: settings.fields.value[group.key as SettingGroupKey],
    })),
);

const environmentFields = computed(
  () => settings.configuration.value?.environment_settings ?? {},
);

function agentDisplayName(agentType: string): string {
  const labels: Record<string, string> = {
    docker_support: "Docker 支持",
    infrastructure_troubleshooter: "基础设施排障",
    auto_orchestration: "智能编排",
  };
  return (
    labels[agentType] ??
    agents.value.find((agent) => agent.agent_type === agentType)
      ?.display_name ??
    agentType
  );
}

function agentDescription(agentType: string): string {
  const descriptions: Record<string, string> = {
    docker_support:
      "负责 Docker 文档问答、配置说明和安全的只读运行时诊断。",
    infrastructure_troubleshooter:
      "负责服务级故障分诊，区分已知事实、可能原因和下一步检查。",
  };
  return (
    descriptions[agentType] ??
    settings.descriptor.value?.description ??
    ""
  );
}

function groupDisplayName(key: string, fallback: string): string {
  const labels: Record<string, string> = {
    model_settings: "模型",
    retrieval_settings: "文档检索",
    runtime_settings: "运行与分诊",
  };
  return labels[key] ?? fallback;
}

function settingLabel(key: string, fallback: string): string {
  const labels: Record<string, string> = {
    model_name: "模型名称",
    temperature: "生成温度",
    max_tokens: "最大输出 Token",
    timeout_seconds: "模型超时时间",
    max_retries: "模型重试次数",
    retry_backoff_seconds: "重试等待时间",
    top_k: "候选文档数量",
    rrf_k: "RRF 平滑参数",
    dense_weight: "向量检索权重",
    keyword_weight: "关键词检索权重",
    rerank_top_k: "重排保留数量",
    context_max_chars: "文档上下文字符上限",
    max_steps: "运行时最大步骤",
    tool_timeout_seconds: "Docker 工具超时",
    logs_max_lines: "日志行数上限",
    evidence_max_chars: "运行时证据字符上限",
    max_hypotheses: "最大假设数量",
    max_next_steps: "最大后续检查数量",
  };
  return labels[key] ?? fallback;
}

function settingDescription(
  key: string,
  fallback: string,
): string {
  const descriptions: Record<string, string> = {
    model_name: "专家调用的 OpenAI 兼容模型标识。",
    temperature: "控制模型回答的随机性；排障场景通常使用较低值。",
    max_tokens: "模型一次回答允许生成的最大 Token 数。",
    timeout_seconds: "单次模型请求允许等待的最长秒数。",
    max_retries: "可重试模型错误发生后允许再次请求的次数。",
    retry_backoff_seconds: "模型重试之间的等待时间（秒）。",
    top_k: "混合检索后进入下一阶段的候选文档数量。",
    rrf_k: "RRF 融合排序的平滑参数。",
    dense_weight: "向量语义检索在混合召回中的权重。",
    keyword_weight: "关键词检索在混合召回中的权重。",
    rerank_top_k: "重排后最终保留给回答模型的文档数量。",
    context_max_chars: "传给回答模型的 Docker 文档上下文最大字符数。",
    max_steps: "一次动态运行时诊断允许执行的最大步骤数。",
    tool_timeout_seconds: "单次只读 Docker 工具调用的超时时间（秒）。",
    logs_max_lines: "一次日志读取最多保留的 Docker 日志行数。",
    evidence_max_chars: "运行时诊断保留并用于回答的最大证据字符数。",
    max_hypotheses: "一次服务故障分诊最多列出的可能原因数量。",
    max_next_steps: "一次服务故障分诊最多给出的下一步检查数量。",
  };
  return descriptions[key] ?? fallback;
}

function capabilityLabel(value: string): string {
  const labels: Record<string, string> = {
    chat: "对话支持",
    documentation_qa: "Docker 文档问答",
    runtime_diagnostics: "运行时诊断",
    multi_agent_supervision: "多 Worker 协作",
    incident_triage: "服务故障分诊",
  };
  return labels[value] ?? value;
}

function toolsetLabel(value: string): string {
  const labels: Record<string, string> = {
    docker_read_only: "Docker 只读工具",
  };
  return labels[value] ?? value;
}

function workerRoleLabel(value: string): string {
  const labels: Record<string, string> = {
    knowledge: "知识检索",
    runtime: "运行时检查",
    diagnosis: "诊断与回答",
    triage: "故障分诊",
  };
  return labels[value] ?? value;
}

function sourceLabel(source: string): string {
  const labels: Record<string, string> = {
    persisted: "自定义覆盖",
    environment: "环境变量",
    default: "应用默认",
  };
  return labels[source] ?? source;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "未设置";
  }
  return String(value);
}

function formatEnvironmentValue(
  field: EffectiveConfigurationField,
): string {
  if (field.secure) {
    return field.configured ? "已配置" : "未配置";
  }
  return formatValue(field.effective_value);
}

function inputType(field: EditableSettingField): "text" | "number" {
  return field.kind === "string" ? "text" : "number";
}

function inputStep(field: EditableSettingField): string | undefined {
  if (field.kind === "integer") {
    return "1";
  }
  if (field.kind === "number") {
    return "any";
  }
  return undefined;
}

function handleOverrideChange(
  field: EditableSettingField,
  event: Event,
): void {
  const target = event.target;
  if (target instanceof HTMLInputElement) {
    settings.setOverride(field, target.checked);
  }
}

async function loadPage(): Promise<void> {
  catalogLoading.value = true;
  catalogError.value = "";
  try {
    agents.value = await listAgents();
    const selected =
      agents.value.find(
        (agent) => agent.agent_type === settings.agentType.value,
      ) ??
      agents.value.find((agent) => agent.default_enabled) ??
      agents.value[0];

    if (selected) {
      await settings.load(selected.agent_type);
    } else {
      catalogError.value = "当前没有可用的专家。";
    }
  } catch (error) {
    catalogError.value =
      error instanceof Error
        ? error.message
        : "无法加载专家列表。";
    await settings.load();
  } finally {
    catalogLoading.value = false;
  }
}

function handleAgentChange(event: Event): void {
  const target = event.target;
  if (!(target instanceof HTMLSelectElement)) {
    return;
  }
  void settings.load(target.value);
}

onMounted(loadPage);
</script>

<template>
  <section class="settings-page">
    <div class="settings-hero panel">
      <div>
        <p class="section-label">专家配置</p>
        <h2>
          {{
            settings.descriptor.value
              ? agentDisplayName(settings.descriptor.value.agent_type)
              : "专家"
          }}
          设置
        </h2>
        <p>
          只保存你确实希望覆盖的配置。未启用“覆盖默认值”的字段会继续继承环境变量或应用默认值。
        </p>
      </div>

      <div class="settings-actions">
        <label class="agent-picker">
          <span>专家</span>
          <select
            :value="settings.agentType.value"
            :disabled="
              catalogLoading ||
              settings.loading.value ||
              settings.saving.value ||
              settings.dirty.value
            "
            @change="handleAgentChange"
          >
            <option
              v-for="agent in agents"
              :key="agent.agent_type"
              :value="agent.agent_type"
            >
              {{ agentDisplayName(agent.agent_type) }}
            </option>
          </select>
        </label>

        <button
          class="button button--ghost"
          type="button"
          :disabled="settings.loading.value || settings.saving.value"
          @click="settings.load()"
        >
          {{ settings.dirty.value ? "放弃修改" : "刷新" }}
        </button>
        <button
          class="button button--primary"
          type="button"
          :disabled="
            !settings.dirty.value ||
            settings.loading.value ||
            settings.saving.value
          "
          @click="settings.save"
        >
          {{ settings.saving.value ? "保存中…" : "保存设置" }}
        </button>
      </div>
    </div>

    <div
      v-if="catalogError"
      class="alert alert--error"
    >
      <span>{{ catalogError }}</span>
      <button
        class="button button--ghost"
        type="button"
        @click="loadPage"
      >
        重新加载专家列表
      </button>
    </div>

    <div
      v-if="settings.errorMessage.value"
      class="alert alert--error alert--dismissible"
    >
      <span>{{ settings.errorMessage.value }}</span>
      <button
        type="button"
        aria-label="关闭错误提示"
        @click="settings.errorMessage.value = ''"
      >
        ×
      </button>
    </div>

    <div
      v-if="settings.successMessage.value"
      class="alert alert--success alert--dismissible"
    >
      <span>{{ settings.successMessage.value }}</span>
      <button
        type="button"
        aria-label="关闭成功提示"
        @click="settings.successMessage.value = ''"
      >
        ×
      </button>
    </div>

    <div
      v-if="settings.loading.value"
      class="panel empty-state"
    >
      正在加载有效配置…
    </div>

    <template v-else-if="settings.configuration.value">
      <section class="settings-summary panel">
        <div class="settings-identity">
          <span
            class="status-dot"
            :class="{
              'status-dot--off': !settings.enabled.value,
            }"
          />
          <label class="settings-name-field">
            <span>显示名称</span>
            <input
              v-model="settings.displayName.value"
              maxlength="120"
              :disabled="settings.saving.value"
            />
          </label>
        </div>

        <label class="toggle-row">
          <input
            v-model="settings.enabled.value"
            type="checkbox"
            :disabled="settings.saving.value"
          />
          <span>
            <strong>启用专家</strong>
            <small>
              停用后将不能发起新的专家会话。
            </small>
          </span>
        </label>

        <div class="settings-summary__meta">
          <span>
            {{
              settings.persisted.value
                ? "已保存自定义配置"
                : "尚未保存自定义配置"
            }}
          </span>
          <span v-if="settings.configuration.value.configuration_updated_at">
            更新时间
            {{
              new Date(
                settings.configuration.value.configuration_updated_at,
              ).toLocaleString()
            }}
          </span>
        </div>
      </section>

      <section
        v-if="settings.descriptor.value"
        class="agent-capability-panel panel"
      >
        <div>
          <p class="section-label">能力</p>
          <h2>{{ agentDisplayName(settings.descriptor.value.agent_type) }}</h2>
          <p>{{ agentDescription(settings.descriptor.value.agent_type) }}</p>
        </div>
        <div class="agent-capability-groups">
          <div>
            <strong>能力</strong>
            <div class="chip-row">
              <span
                v-for="item in settings.descriptor.value.capabilities"
                :key="`settings-capability-${item}`"
                class="chip"
              >
                {{ capabilityLabel(item) }}
              </span>
            </div>
          </div>
          <div>
            <strong>工具集</strong>
            <div class="chip-row">
              <span
                v-for="item in settings.descriptor.value.toolsets"
                :key="`settings-toolset-${item}`"
                class="chip"
              >
                {{ toolsetLabel(item) }}
              </span>
              <span
                v-if="settings.descriptor.value.toolsets.length === 0"
                class="muted"
              >
                暂无
              </span>
            </div>
          </div>
          <div>
            <strong>工作角色</strong>
            <div class="chip-row">
              <span
                v-for="item in settings.descriptor.value.worker_roles"
                :key="`settings-worker-${item}`"
                class="chip"
              >
                {{ workerRoleLabel(item) }}
              </span>
            </div>
          </div>
        </div>
      </section>

      <section
        v-for="group in editableGroups"
        :key="group.key"
        class="settings-group panel"
      >
        <div class="panel__header">
          <div>
            <p class="section-label">可编辑配置</p>
            <h2>{{ groupDisplayName(group.key, group.label) }}</h2>
          </div>
        </div>

        <div class="setting-editor-list">
          <article
            v-for="field in group.fields"
            :key="field.key"
            class="setting-editor"
            :class="{ 'setting-editor--override': field.override }"
          >
            <div class="setting-editor__info">
              <div class="setting-editor__title">
                <div>
                  <strong>{{ settingLabel(field.key, field.label) }}</strong>
                  <code>{{ field.key }}</code>
                </div>
                <label class="override-toggle">
                  <input
                    :checked="field.override"
                    type="checkbox"
                    :disabled="settings.saving.value"
                    @change="handleOverrideChange(field, $event)"
                  />
                  <span>覆盖默认值</span>
                </label>
              </div>

              <p>{{ settingDescription(field.key, field.description) }}</p>

              <div class="setting-editor__source">
                <span
                  class="source-badge"
                  :data-source="field.effective.source"
                >
                  当前来源： {{ sourceLabel(field.effective.source) }}
                </span>
                <span>
                  生效值：
                  <strong>
                    {{ formatValue(field.effective.effective_value) }}
                  </strong>
                </span>
                <span>
                  继承值：
                  <strong>
                    {{ formatValue(settings.fallbackValue(field)) }}
                  </strong>
                </span>
              </div>
            </div>

            <div class="setting-editor__control">
              <input
                v-model="field.input"
                :type="inputType(field)"
                :step="inputStep(field)"
                :min="field.minimum ?? undefined"
                :max="field.maximum ?? undefined"
                :disabled="!field.override || settings.saving.value"
                :aria-invalid="Boolean(field.error)"
              />
              <span v-if="field.error" class="field-error">
                {{ field.error }}
              </span>
              <span v-else-if="!field.override" class="field-hint">
                正在继承 {{ formatValue(settings.fallbackValue(field)) }}
              </span>
              <span v-else class="field-hint">
                该值将被持久化保存。
              </span>
            </div>
          </article>
        </div>
      </section>

      <section class="settings-group panel">
        <div class="panel__header">
          <div>
            <p class="section-label">只读运行环境</p>
            <h2>环境与基础设施</h2>
          </div>
        </div>

        <div class="settings-table">
          <div class="settings-table__head">
            <span>字段</span>
            <span>生效值</span>
            <span>来源</span>
            <span>访问方式</span>
          </div>

          <div
            v-for="(field, name) in environmentFields"
            :key="name"
            class="settings-table__row"
          >
            <code>{{ name }}</code>
            <strong>{{ formatEnvironmentValue(field) }}</strong>
            <span
              class="source-badge"
              :data-source="field.source"
            >
              {{ sourceLabel(field.source) }}
            </span>
            <span>
              {{
                field.secure
                  ? "安全字段 / 已隐藏"
                  : "由环境变量管理"
              }}
            </span>
          </div>
        </div>
      </section>
    </template>
  </section>
</template>
