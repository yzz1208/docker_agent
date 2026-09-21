import { computed, ref } from "vue";

import {
  ApiError,
  createAgentConfiguration,
  getEffectiveAgentConfiguration,
  updateAgentConfiguration,
} from "../lib/api";
import type {
  AgentConfigurationCreate,
  AgentConfigurationMutation,
  ConfigurationScalar,
  EffectiveAgentConfiguration,
  EffectiveConfigurationField,
} from "../lib/types";

export type SettingGroupKey =
  | "model_settings"
  | "retrieval_settings"
  | "runtime_settings";

type SettingValueKind = "string" | "integer" | "number";

type SettingSpec = {
  key: string;
  label: string;
  description: string;
  kind: SettingValueKind;
  minimum?: number;
  maximum?: number;
};

export type EditableSettingField = SettingSpec & {
  override: boolean;
  input: string;
  effective: EffectiveConfigurationField;
  error: string;
};

const GROUP_SPECS: Record<SettingGroupKey, SettingSpec[]> = {
  model_settings: [
    {
      key: "model_name",
      label: "Model name",
      description: "OpenAI-compatible model identifier used by the agent.",
      kind: "string",
    },
    {
      key: "temperature",
      label: "Temperature",
      description: "Sampling temperature for model responses.",
      kind: "number",
      minimum: 0,
      maximum: 2,
    },
    {
      key: "max_tokens",
      label: "Max tokens",
      description: "Maximum generated tokens when the provider supports it.",
      kind: "integer",
      minimum: 1,
    },
    {
      key: "timeout_seconds",
      label: "Model timeout",
      description: "Maximum seconds allowed for one model request.",
      kind: "number",
      minimum: 0.001,
    },
    {
      key: "max_retries",
      label: "Model retries",
      description: "Retry attempts after a retryable model failure.",
      kind: "integer",
      minimum: 0,
    },
    {
      key: "retry_backoff_seconds",
      label: "Retry backoff",
      description: "Delay between model retries in seconds.",
      kind: "number",
      minimum: 0,
    },
  ],
  retrieval_settings: [
    {
      key: "top_k",
      label: "Candidate top K",
      description: "Hybrid retrieval candidates kept before reranking.",
      kind: "integer",
      minimum: 1,
    },
    {
      key: "rrf_k",
      label: "RRF K",
      description: "Reciprocal-rank-fusion smoothing constant.",
      kind: "integer",
      minimum: 0,
    },
    {
      key: "dense_weight",
      label: "Dense weight",
      description: "Weight applied to dense retrieval ranking.",
      kind: "number",
      minimum: 0,
    },
    {
      key: "keyword_weight",
      label: "Keyword weight",
      description: "Weight applied to keyword retrieval ranking.",
      kind: "number",
      minimum: 0,
    },
    {
      key: "rerank_top_k",
      label: "Rerank top K",
      description: "Final candidates retained after reranking.",
      kind: "integer",
      minimum: 1,
    },
    {
      key: "context_max_chars",
      label: "Context max chars",
      description: "Maximum documentation context passed to the answer model.",
      kind: "integer",
      minimum: 1,
    },
  ],
  runtime_settings: [
    {
      key: "max_steps",
      label: "Runtime max steps",
      description: "Maximum dynamic runtime workflow steps.",
      kind: "integer",
      minimum: 1,
    },
    {
      key: "tool_timeout_seconds",
      label: "Docker tool timeout",
      description: "Maximum seconds allowed for one Docker tool call.",
      kind: "number",
      minimum: 0.001,
    },
    {
      key: "logs_max_lines",
      label: "Log line limit",
      description: "Maximum Docker log lines collected per tool call.",
      kind: "integer",
      minimum: 1,
    },
    {
      key: "evidence_max_chars",
      label: "Evidence max chars",
      description: "Maximum runtime evidence characters retained for synthesis.",
      kind: "integer",
      minimum: 1,
    },
  ],
};

export const SETTING_GROUP_LABELS: Record<SettingGroupKey, string> = {
  model_settings: "Model",
  retrieval_settings: "Retrieval",
  runtime_settings: "Runtime",
};

function displayValue(value: ConfigurationScalar): string {
  return value === null ? "" : String(value);
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

function parseField(field: EditableSettingField): ConfigurationScalar {
  const raw = field.input.trim();

  if (field.kind === "string") {
    if (!raw) {
      throw new Error(`${field.label} must not be empty.`);
    }
    return raw;
  }

  if (!raw) {
    throw new Error(`${field.label} must not be empty.`);
  }

  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) {
    throw new Error(`${field.label} must be a number.`);
  }
  if (field.kind === "integer" && !Number.isInteger(parsed)) {
    throw new Error(`${field.label} must be an integer.`);
  }
  if (field.minimum !== undefined && parsed < field.minimum) {
    throw new Error(
      `${field.label} must be at least ${field.minimum}.`,
    );
  }
  if (field.maximum !== undefined && parsed > field.maximum) {
    throw new Error(
      `${field.label} must not exceed ${field.maximum}.`,
    );
  }
  return parsed;
}

export function useAgentSettings() {
  const configuration = ref<EffectiveAgentConfiguration | null>(null);
  const displayName = ref("Docker Support");
  const enabled = ref(true);
  const fields = ref<Record<SettingGroupKey, EditableSettingField[]>>({
    model_settings: [],
    retrieval_settings: [],
    runtime_settings: [],
  });

  const loading = ref(false);
  const saving = ref(false);
  const errorMessage = ref("");
  const successMessage = ref("");
  const baseline = ref("");

  const persisted = computed(
    () => configuration.value?.persisted ?? false,
  );

  const dirty = computed(
    () => Boolean(configuration.value) && snapshot() !== baseline.value,
  );

  function hydrate(next: EffectiveAgentConfiguration): void {
    configuration.value = next;
    displayName.value = next.display_name;
    enabled.value = next.enabled;

    const nextFields = {} as Record<
      SettingGroupKey,
      EditableSettingField[]
    >;

    for (const groupKey of Object.keys(GROUP_SPECS) as SettingGroupKey[]) {
      const effectiveGroup = next[groupKey];
      nextFields[groupKey] = GROUP_SPECS[groupKey].map((spec) => {
        const effective = effectiveGroup[spec.key];
        if (!effective) {
          throw new Error(
            `Effective configuration is missing ${groupKey}.${spec.key}.`,
          );
        }
        return {
          ...spec,
          override: effective.persisted_value !== null,
          input: displayValue(
            effective.persisted_value ?? effective.effective_value,
          ),
          effective,
          error: "",
        };
      });
    }

    fields.value = nextFields;
    baseline.value = snapshot();
  }

  async function load(): Promise<void> {
    loading.value = true;
    errorMessage.value = "";
    successMessage.value = "";
    try {
      const next = await getEffectiveAgentConfiguration(
        "docker_support",
      );
      hydrate(next);
    } catch (error) {
      errorMessage.value = errorText(error);
    } finally {
      loading.value = false;
    }
  }

  function fallbackValue(field: EditableSettingField): ConfigurationScalar {
    return field.effective.base_value;
  }

  function setOverride(
    field: EditableSettingField,
    override: boolean,
  ): void {
    field.override = override;
    field.error = "";
    if (override && !field.input.trim()) {
      field.input = displayValue(
        field.effective.persisted_value ??
          field.effective.effective_value ??
          field.effective.base_value,
      );
    }
  }

  function validate(): boolean {
    let valid = true;
    errorMessage.value = "";

    if (!displayName.value.trim()) {
      errorMessage.value = "Display name must not be empty.";
      valid = false;
    }

    for (const group of Object.values(fields.value)) {
      for (const field of group) {
        field.error = "";
        if (!field.override) {
          continue;
        }
        try {
          parseField(field);
        } catch (error) {
          field.error = errorText(error);
          valid = false;
        }
      }
    }

    const retrieval = fields.value.retrieval_settings;
    const topK = resolvedNumber(retrieval, "top_k");
    const rerankTopK = resolvedNumber(retrieval, "rerank_top_k");
    if (
      topK !== null &&
      rerankTopK !== null &&
      rerankTopK > topK
    ) {
      const field = retrieval.find(
        (item) => item.key === "rerank_top_k",
      );
      if (field) {
        field.error = "Rerank top K must not exceed candidate top K.";
      }
      valid = false;
    }

    const denseWeight = resolvedNumber(retrieval, "dense_weight");
    const keywordWeight = resolvedNumber(
      retrieval,
      "keyword_weight",
    );
    if (denseWeight === 0 && keywordWeight === 0) {
      const field = retrieval.find(
        (item) => item.key === "keyword_weight",
      );
      if (field) {
        field.error =
          "Dense weight and keyword weight cannot both be zero.";
      }
      valid = false;
    }

    return valid;
  }

  function resolvedNumber(
    group: EditableSettingField[],
    key: string,
  ): number | null {
    const field = group.find((item) => item.key === key);
    if (!field) {
      return null;
    }
    const value = field.override
      ? safeParse(field)
      : fallbackValue(field);
    return typeof value === "number" ? value : null;
  }

  function safeParse(
    field: EditableSettingField,
  ): ConfigurationScalar {
    try {
      return parseField(field);
    } catch {
      return null;
    }
  }

  function buildGroup(
    groupKey: SettingGroupKey,
  ): Record<string, unknown> {
    const result: Record<string, unknown> = {};
    for (const field of fields.value[groupKey]) {
      if (field.override) {
        result[field.key] = parseField(field);
      }
    }
    return result;
  }

  function buildMutation(): AgentConfigurationMutation {
    return {
      display_name: displayName.value.trim(),
      enabled: enabled.value,
      model_settings: buildGroup("model_settings"),
      retrieval_settings: buildGroup("retrieval_settings"),
      runtime_settings: buildGroup("runtime_settings"),
    };
  }

  async function save(): Promise<boolean> {
    successMessage.value = "";
    if (!validate() || saving.value) {
      return false;
    }

    saving.value = true;
    errorMessage.value = "";

    try {
      const mutation = buildMutation();
      if (persisted.value) {
        await updateAgentConfiguration("docker_support", mutation);
      } else {
        const createBody: AgentConfigurationCreate = {
          agent_type: "docker_support",
          display_name: mutation.display_name ?? "Docker Support",
          enabled: mutation.enabled ?? true,
          model_settings: mutation.model_settings ?? {},
          retrieval_settings: mutation.retrieval_settings ?? {},
          runtime_settings: mutation.runtime_settings ?? {},
        };
        await createAgentConfiguration(createBody);
      }

      const next = await getEffectiveAgentConfiguration(
        "docker_support",
      );
      hydrate(next);
      successMessage.value = "Agent settings saved and applied to new sessions.";
      return true;
    } catch (error) {
      errorMessage.value = errorText(error);
      return false;
    } finally {
      saving.value = false;
    }
  }

  function snapshot(): string {
    return JSON.stringify({
      displayName: displayName.value,
      enabled: enabled.value,
      fields: (Object.keys(fields.value) as SettingGroupKey[]).map(
        (groupKey) => ({
          groupKey,
          fields: fields.value[groupKey].map((field) => ({
            key: field.key,
            override: field.override,
            input: field.input,
          })),
        }),
      ),
    });
  }

  return {
    configuration,
    displayName,
    enabled,
    fields,
    loading,
    saving,
    errorMessage,
    successMessage,
    persisted,
    dirty,
    load,
    save,
    setOverride,
    fallbackValue,
  };
}
