import { computed, ref } from "vue";

import {
  ApiError,
  createAgentConfiguration,
  getAgentDescriptor,
  getEffectiveAgentConfiguration,
  updateAgentConfiguration,
} from "../lib/api";
import type {
  AgentConfigurationCreate,
  AgentConfigurationMutation,
  AgentDescriptor,
  ConfigurationFieldDescriptor,
  ConfigurationRuleDescriptor,
  ConfigurationScalar,
  EffectiveAgentConfiguration,
  EffectiveConfigurationField,
} from "../lib/types";

export type SettingGroupKey =
  | "model_settings"
  | "retrieval_settings"
  | "runtime_settings";

export type EditableSettingField = ConfigurationFieldDescriptor & {
  override: boolean;
  input: string;
  effective: EffectiveConfigurationField;
  error: string;
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

function isSettingGroupKey(value: string): value is SettingGroupKey {
  return (
    value === "model_settings" ||
    value === "retrieval_settings" ||
    value === "runtime_settings"
  );
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
  if (
    field.minimum !== null &&
    parsed < field.minimum
  ) {
    throw new Error(
      `${field.label} must be at least ${field.minimum}.`,
    );
  }
  if (
    field.maximum !== null &&
    parsed > field.maximum
  ) {
    throw new Error(
      `${field.label} must not exceed ${field.maximum}.`,
    );
  }
  return parsed;
}

export function useAgentSettings(
  initialAgentType = "docker_support",
) {
  const agentType = ref(initialAgentType);
  const descriptor = ref<AgentDescriptor | null>(null);
  const configuration = ref<EffectiveAgentConfiguration | null>(null);
  const displayName = ref("");
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

  function hydrate(
    nextDescriptor: AgentDescriptor,
    next: EffectiveAgentConfiguration,
  ): void {
    descriptor.value = nextDescriptor;
    configuration.value = next;
    displayName.value = next.display_name;
    enabled.value = next.enabled;

    const nextFields: Record<
      SettingGroupKey,
      EditableSettingField[]
    > = {
      model_settings: [],
      retrieval_settings: [],
      runtime_settings: [],
    };

    for (const group of nextDescriptor.configuration_schema) {
      if (!isSettingGroupKey(group.key)) {
        throw new Error(
          `Unsupported configuration group ${group.key}.`,
        );
      }
      const effectiveGroup = next[group.key];
      nextFields[group.key] = group.fields.map((spec) => {
        const effective = effectiveGroup[spec.key];
        if (!effective) {
          throw new Error(
            `Effective configuration is missing ${group.key}.${spec.key}.`,
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

  async function load(nextAgentType?: string): Promise<void> {
    const currentAgentType = (
      nextAgentType ?? agentType.value
    ).trim();
    if (!currentAgentType) {
      errorMessage.value = "Agent type must not be empty.";
      return;
    }

    loading.value = true;
    errorMessage.value = "";
    successMessage.value = "";
    try {
      const [nextDescriptor, next] = await Promise.all([
        getAgentDescriptor(currentAgentType),
        getEffectiveAgentConfiguration(currentAgentType),
      ]);
      agentType.value = currentAgentType;
      hydrate(nextDescriptor, next);
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

    for (const rule of descriptor.value?.configuration_rules ?? []) {
      if (!validateRule(rule)) {
        valid = false;
      }
    }

    return valid;
  }

  function validateRule(rule: ConfigurationRuleDescriptor): boolean {
    if (!isSettingGroupKey(rule.group)) {
      return false;
    }
    const group = fields.value[rule.group];
    const target = group.find(
      (field) => field.key === rule.target_field,
    );
    const values = rule.fields.map((key) =>
      resolvedNumber(group, key),
    );

    if (values.some((value) => value === null)) {
      return true;
    }

    let failed = false;
    if (rule.kind === "less_equal") {
      failed = (
        values.length === 2 &&
        (values[0] as number) > (values[1] as number)
      );
    } else if (rule.kind === "not_all_zero") {
      failed = values.every((value) => value === 0);
    }

    if (failed && target) {
      target.error = rule.message;
    }
    return !failed;
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
        await updateAgentConfiguration(agentType.value, mutation);
      } else {
        const createBody: AgentConfigurationCreate = {
          agent_type: agentType.value,
          display_name:
            mutation.display_name ??
            descriptor.value?.display_name ??
            agentType.value,
          enabled:
            mutation.enabled ??
            descriptor.value?.default_enabled ??
            true,
          model_settings: mutation.model_settings ?? {},
          retrieval_settings: mutation.retrieval_settings ?? {},
          runtime_settings: mutation.runtime_settings ?? {},
        };
        await createAgentConfiguration(createBody);
      }

      const next = await getEffectiveAgentConfiguration(agentType.value);
      if (!descriptor.value) {
        throw new Error("Agent descriptor is unavailable.");
      }
      hydrate(descriptor.value, next);
      successMessage.value =
        "Agent settings saved and applied to new sessions.";
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
      agentType: agentType.value,
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
    agentType,
    descriptor,
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
