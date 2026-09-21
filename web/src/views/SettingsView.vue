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

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "Not set";
  }
  return String(value);
}

function formatEnvironmentValue(
  field: EffectiveConfigurationField,
): string {
  if (field.secure) {
    return field.configured ? "Configured" : "Not configured";
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
      catalogError.value = "No registered Agents are available.";
    }
  } catch (error) {
    catalogError.value =
      error instanceof Error
        ? error.message
        : "Could not load the Agent catalog.";
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
        <p class="section-label">Agent configuration</p>
        <h2>
          {{
            settings.descriptor.value?.display_name ??
            "Agent"
          }}
          settings
        </h2>
        <p>
          Persist only the preferences you want to override. Fields without
          an override continue to inherit their environment or application
          default value.
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
              {{ agent.display_name }}
            </option>
          </select>
        </label>

        <button
          class="button button--ghost"
          type="button"
          :disabled="settings.loading.value || settings.saving.value"
          @click="settings.load"
        >
          {{ settings.dirty.value ? "Discard changes" : "Refresh" }}
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
          {{ settings.saving.value ? "Saving…" : "Save settings" }}
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
        Retry Agent catalog
      </button>
    </div>

    <div
      v-if="settings.errorMessage.value"
      class="alert alert--error alert--dismissible"
    >
      <span>{{ settings.errorMessage.value }}</span>
      <button
        type="button"
        aria-label="Dismiss error"
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
        aria-label="Dismiss success message"
        @click="settings.successMessage.value = ''"
      >
        ×
      </button>
    </div>

    <div
      v-if="settings.loading.value"
      class="panel empty-state"
    >
      Loading effective configuration…
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
            <span>Display name</span>
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
            <strong>Agent enabled</strong>
            <small>
              Disabled agents cannot start new sessions.
            </small>
          </span>
        </label>

        <div class="settings-summary__meta">
          <span>
            {{
              settings.persisted.value
                ? "Persisted configuration"
                : "No saved preferences yet"
            }}
          </span>
          <span v-if="settings.configuration.value.configuration_updated_at">
            Updated
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
          <p class="section-label">Capabilities</p>
          <h2>{{ settings.descriptor.value.display_name }}</h2>
          <p>{{ settings.descriptor.value.description }}</p>
        </div>
        <div class="agent-capability-groups">
          <div>
            <strong>Capabilities</strong>
            <div class="chip-row">
              <span
                v-for="item in settings.descriptor.value.capabilities"
                :key="`settings-capability-${item}`"
                class="chip"
              >
                {{ item }}
              </span>
            </div>
          </div>
          <div>
            <strong>Toolsets</strong>
            <div class="chip-row">
              <span
                v-for="item in settings.descriptor.value.toolsets"
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
            <strong>Worker roles</strong>
            <div class="chip-row">
              <span
                v-for="item in settings.descriptor.value.worker_roles"
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
            <p class="section-label">Editable preferences</p>
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
                    @change="handleOverrideChange(field, $event)"
                  />
                  <span>Override</span>
                </label>
              </div>

              <p>{{ field.description }}</p>

              <div class="setting-editor__source">
                <span
                  class="source-badge"
                  :data-source="field.effective.source"
                >
                  current: {{ field.effective.source }}
                </span>
                <span>
                  Effective:
                  <strong>
                    {{ formatValue(field.effective.effective_value) }}
                  </strong>
                </span>
                <span>
                  Inherited:
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
                :min="field.minimum"
                :max="field.maximum"
                :disabled="!field.override || settings.saving.value"
                :aria-invalid="Boolean(field.error)"
              />
              <span v-if="field.error" class="field-error">
                {{ field.error }}
              </span>
              <span v-else-if="!field.override" class="field-hint">
                Inheriting {{ formatValue(settings.fallbackValue(field)) }}
              </span>
              <span v-else class="field-hint">
                This value will be persisted.
              </span>
            </div>
          </article>
        </div>
      </section>

      <section class="settings-group panel">
        <div class="panel__header">
          <div>
            <p class="section-label">Read-only runtime infrastructure</p>
            <h2>Environment / infrastructure</h2>
          </div>
        </div>

        <div class="settings-table">
          <div class="settings-table__head">
            <span>Field</span>
            <span>Effective value</span>
            <span>Source</span>
            <span>Access</span>
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
                  ? "Secure / redacted"
                  : "Environment owned"
              }}
            </span>
          </div>
        </div>
      </section>
    </template>
  </section>
</template>
