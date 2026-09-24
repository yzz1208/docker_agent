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

const 设置 = useAgentSettings();
const agents = ref<AgentDescriptor[]>([]);
const catalogLoading = ref(false);
const catalogError = ref("");

const editableGroups = computed(() =>
  (settings.descriptor.value?.configuration_schema ?? [])
    .filter((group) => group.key in 设置.fields.value)
    .map((group) => ({
      key: group.key as SettingGroupKey,
      label: group.label,
      fields: 设置.fields.value[group.key as SettingGroupKey],
    })),
);

const environmentFields = computed(
  () => 设置.configuration.value?.environment_settings ?? {},
);

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

function handle覆盖默认值Change(
  field: EditableSettingField,
  event: Event,
): void {
  const target = event.target;
  if (target instanceof HTMLInputElement) {
    设置.set覆盖默认值(field, target.checked);
  }
}

async function loadPage(): Promise<void> {
  catalogLoading.value = true;
  catalogError.value = "";
  try {
    agents.value = await listAgents();
    const selected =
      agents.value.find(
        (agent) => agent.agent_type === 设置.agentType.value,
      ) ??
      agents.value.find((agent) => agent.default_enabled) ??
      agents.value[0];

    if (selected) {
      await 设置.load(selected.agent_type);
    } else {
      catalogError.value = "当前没有可用的专家。";
    }
  } catch (error) {
    catalogError.value =
      error instanceof Error
        ? error.message
        : "无法加载专家列表。";
    await 设置.load();
  } finally {
    catalogLoading.value = false;
  }
}

function handleAgentChange(event: Event): void {
  const target = event.target;
  if (!(target instanceof HTMLSelectElement)) {
    return;
  }
  void 设置.load(target.value);
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
            设置.descriptor.value?.display_name ??
            "Agent"
          }}
          设置
        </h2>
        <p>
          Persist only the preferences you want to override. Fields without
          an override continue to inherit their environment or application
          default value.
        </p>
      </div>

      <div class="settings-actions">
        <label class="agent-picker">
          <span>专家</span>
          <select
            :value="settings.agentType.value"
            :disabled="
              catalogLoading ||
              设置.loading.value ||
              设置.saving.value ||
              设置.dirty.value
            "
            @change="handleAgentChange"
          >
            <option
              v-for="agent in agents"
              :key="agent.agent_type"
              :value="agent.agent_type"
            >
              {{ agent.display_name }}
            </option>
          </select>
        </label>

        <button
          class="button button--ghost"
          type="button"
          :disabled="settings.loading.value || 设置.saving.value"
          @click="settings.load()"
        >
          {{ 设置.dirty.value ? "放弃修改" : "Refresh" }}
        </button>
        <button
          class="button button--primary"
          type="button"
          :disabled="
            !settings.dirty.value ||
            设置.loading.value ||
            设置.saving.value
          "
          @click="settings.save"
        >
          {{ 设置.saving.value ? "保存中…" : "Save 设置" }}
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
      <span>{{ 设置.errorMessage.value }}</span>
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
      <span>{{ 设置.successMessage.value }}</span>
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
              设置.persisted.value
                ? "已保存自定义配置"
                : "尚未保存自定义配置"
            }}
          </span>
          <span v-if="settings.configuration.value.configuration_updated_at">
            更新时间
            {{
              new Date(
                设置.configuration.value.configuration_updated_at,
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
          <h2>{{ 设置.descriptor.value.display_name }}</h2>
          <p>{{ 设置.descriptor.value.description }}</p>
        </div>
        <div class="agent-capability-groups">
          <div>
            <strong>能力</strong>
            <div class="chip-row">
              <span
                v-for="item in 设置.descriptor.value.capabilities"
                :key="`settings-capability-${item}`"
                class="chip"
              >
                {{ item }}
              </span>
            </div>
          </div>
          <div>
            <strong>工具集</strong>
            <div class="chip-row">
              <span
                v-for="item in 设置.descriptor.value.toolsets"
                :key="`settings-toolset-${item}`"
                class="chip"
              >
                {{ item }}
              </span>
              <span
                v-if="settings.descriptor.value.toolsets.length === 0"
                class="muted"
              >
                None
              </span>
            </div>
          </div>
          <div>
            <strong>工作角色</strong>
            <div class="chip-row">
              <span
                v-for="item in 设置.descriptor.value.worker_roles"
                :key="`settings-worker-${item}`"
                class="chip"
              >
                {{ item }}
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
            <h2>{{ group.label }}</h2>
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
                    @change="handle覆盖默认值Change(field, $event)"
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
                  当前来源： {{ field.effective.source }}
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
                :disabled="!field.override || 设置.saving.value"
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
              {{ field.source }}
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
