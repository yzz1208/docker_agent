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
  return {
    docker_support: "Docker 支持",
    infrastructure_troubleshooter: "基础设施排障",
    auto_orchestration: "智能编排",
  }[agentType] ?? agentType;
}

function capabilityDisplayName(value: string): string {
  return {
    chat: "对话",
    documentation_qa: "文档问答",
    runtime_diagnostics: "运行时诊断",
    incident_triage: "故障分诊",
    multi_agent_supervision: "多智能体监督",
  }[value] ?? value;
}

function workerDisplayName(value: string): string {
  return {
    knowledge: "知识检索",
    runtime: "运行时检查",
    diagnosis: "分析诊断",
    triage: "故障分诊",
  }[value] ?? value;
}

function sourceDisplayName(value: string): string {
  return {
    persisted: "已保存覆盖值",
    environment: "环境变量",
    default: "默认值",
  }[value] ?? value;
}

function groupDisplayName(value: string): string {
  return {
    model: "模型设置",
    retrieval: "检索设置",
    runtime: "运行时设置",
  }[value] ?? value;
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
      catalogError.value = "当前没有可用的 Agent。";
    }
  } catch (error) {
    catalogError.value =
      error instanceof Error
        ? error.message
        : "无法加载 Agent 列表。";
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
        <p class="section-label">Agent 配置</p>
        <h2>
          {{
            settings.descriptor.value
              ? agentDisplayName(settings.descriptor.value.agent_type)
              : "Agent"
          }}
          设置
        </h2>
        <p>
          只保存你希望覆盖的配置；未覆盖的字段会继续继承环境变量或应用默认值。
        </p>
      </div>

      <div class="settings-actions">
        <label class="agent-picker">
          <span>Agent</span>
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
        重新加载 Agent
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
      正在加载生效配置…
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
            <strong>启用 Agent</strong>
            <small>
              禁用后，该 Agent 不能启动新的会话。
            </small>
          </span>
        </label>

        <div class="settings-summary__meta">
          <span>
            {{
              settings.persisted.value
                ? "已保存自定义配置"
                : "当前使用默认配置"
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
          <p>{{ settings.descriptor.value.description }}</p>
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
                {{ capabilityDisplayName(item) }}
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
                {{ capabilityDisplayName(item) }}
              </span>
              <span
                v-if="settings.descriptor.value.toolsets.length === 0"
                class="muted"
              >
                无
              </span>
            </div>
          </div>
          <div>
            <strong>Worker 角色</strong>
            <div class="chip-row">
              <span
                v-for="item in settings.descriptor.value.worker_roles"
                :key="`settings-worker-${item}`"
                class="chip"
              >
                {{ workerDisplayName(item) }}
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
            <p class="section-label">可编辑偏好</p>
            <h2>{{ groupDisplayName(group.key) }}</h2>
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
                  <strong>{{ field.label }}</strong>
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

              <p>{{ field.description }}</p>

              <div class="setting-editor__source">
                <span
                  class="source-badge"
                  :data-source="field.effective.source"
                >
                  当前来源：{{ sourceDisplayName(field.effective.source) }}
                </span>
                <span>
                  当前生效：
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
                该值会被持久化保存。
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
              {{ sourceDisplayName(field.source) }}
            </span>
            <span>
              {{
                field.secure
                  ? "敏感配置 / 已脱敏"
                  : "由环境变量管理"
              }}
            </span>
          </div>
        </div>
      </section>
    </template>
  </section>
</template>
