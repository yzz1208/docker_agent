<script setup lang="ts">
import { computed, onMounted } from "vue";

import {
  SETTING_GROUP_LABELS,
  type EditableSettingField,
  type SettingGroupKey,
  useAgentSettings,
} from "../composables/useAgentSettings";
import type { EffectiveConfigurationField } from "../lib/types";

const settings = useAgentSettings();

const editableGroups = computed(
  () =>
    (
      Object.keys(SETTING_GROUP_LABELS) as SettingGroupKey[]
    ).map((key) => ({
      key,
      label: SETTING_GROUP_LABELS[key],
      fields: settings.fields.value[key],
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

onMounted(settings.load);
</script>

<template>
  <section class="settings-page">
    <div class="settings-hero panel">
      <div>
        <p class="section-label">Agent configuration</p>
        <h2>Docker Support settings</h2>
        <p>
          Persist only the preferences you want to override. Fields without
          an override continue to inherit their environment or application
          default value.
        </p>
      </div>

      <div class="settings-actions">
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
