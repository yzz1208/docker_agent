<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { ApiError, getEffectiveAgentConfiguration } from "../lib/api";
import type {
  EffectiveAgentConfiguration,
  EffectiveConfigurationField,
} from "../lib/types";

const configuration = ref<EffectiveAgentConfiguration | null>(null);
const loading = ref(false);
const errorMessage = ref("");

const groups = computed(() => {
  if (!configuration.value) {
    return [];
  }

  return [
    ["Model", configuration.value.model_settings],
    ["Retrieval", configuration.value.retrieval_settings],
    ["Runtime", configuration.value.runtime_settings],
    ["Environment / infrastructure", configuration.value.environment_settings],
  ] as const;
});

function formatValue(field: EffectiveConfigurationField): string {
  if (field.secure) {
    return field.configured ? "Configured" : "Not configured";
  }
  if (field.effective_value === null) {
    return "Not set";
  }
  return String(field.effective_value);
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    return error.detail;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Something went wrong.";
}

async function loadConfiguration(): Promise<void> {
  loading.value = true;
  errorMessage.value = "";
  try {
    configuration.value = await getEffectiveAgentConfiguration(
      "docker_support",
    );
  } catch (error) {
    errorMessage.value = errorText(error);
  } finally {
    loading.value = false;
  }
}

onMounted(loadConfiguration);
</script>

<template>
  <section class="settings-page">
    <div class="settings-hero panel">
      <div>
        <p class="section-label">Agent configuration</p>
        <h2>Effective Docker Support settings</h2>
        <p>
          Inspect the value the runtime actually uses and where it comes from.
          Secure fields are intentionally redacted by the backend.
        </p>
      </div>
      <button class="button button--ghost" @click="loadConfiguration">
        Refresh
      </button>
    </div>

    <div v-if="errorMessage" class="alert alert--error">
      {{ errorMessage }}
    </div>

    <div v-if="loading" class="panel empty-state">
      Loading effective configuration…
    </div>

    <template v-else-if="configuration">
      <section class="settings-summary panel">
        <div>
          <span class="status-dot" :class="{ 'status-dot--off': !configuration.enabled }" />
          <strong>{{ configuration.display_name }}</strong>
        </div>
        <div class="settings-summary__meta">
          <span>
            {{ configuration.enabled ? "Enabled" : "Disabled" }}
          </span>
          <span>
            {{ configuration.persisted ? "Persisted overrides" : "Defaults only" }}
          </span>
        </div>
      </section>

      <section
        v-for="[label, fields] in groups"
        :key="label"
        class="settings-group panel"
      >
        <div class="panel__header">
          <div>
            <p class="section-label">Configuration group</p>
            <h2>{{ label }}</h2>
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
            v-for="(field, name) in fields"
            :key="name"
            class="settings-table__row"
          >
            <code>{{ name }}</code>
            <strong>{{ formatValue(field) }}</strong>
            <span class="source-badge" :data-source="field.source">
              {{ field.source }}
            </span>
            <span>
              {{ field.editable ? "Editable" : "Environment owned" }}
            </span>
          </div>
        </div>
      </section>
    </template>
  </section>
</template>
