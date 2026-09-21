import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AgentDescriptor,
  EffectiveAgentConfiguration,
  EffectiveConfigurationField,
} from "../lib/types";

vi.mock("../lib/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    detail: string;

    constructor(status: number, detail: string) {
      super(detail);
      this.status = status;
      this.detail = detail;
    }
  },
  createAgentConfiguration: vi.fn(),
  getAgentDescriptor: vi.fn(),
  getEffectiveAgentConfiguration: vi.fn(),
  updateAgentConfiguration: vi.fn(),
}));

import {
  createAgentConfiguration,
  getAgentDescriptor,
  getEffectiveAgentConfiguration,
  updateAgentConfiguration,
} from "../lib/api";
import { useAgentSettings } from "./useAgentSettings";

function field(
  value: string | number | boolean | null,
): EffectiveConfigurationField {
  return {
    persisted_value: null,
    base_value: value,
    effective_value: value,
    source: "default",
    editable: true,
    secure: false,
    configured: value !== null && value !== "",
  };
}

function agentDescriptor(): AgentDescriptor {
  return {
    agent_type: "docker_support",
    display_name: "Docker Support",
    description: "Docker support",
    capabilities: ["chat"],
    knowledge_sources: ["docker_docs"],
    toolsets: ["docker_read_only"],
    worker_roles: ["knowledge"],
    configuration_groups: [
      "model_settings",
      "retrieval_settings",
      "runtime_settings",
    ],
    configuration_schema: [
      {
        key: "model_settings",
        label: "Model",
        fields: [
          {
            key: "model_name",
            label: "Model name",
            description: "Model identifier",
            kind: "string",
            minimum: null,
            maximum: null,
          },
          {
            key: "temperature",
            label: "Sampling temperature",
            description: "Model sampling temperature",
            kind: "number",
            minimum: 0,
            maximum: 2,
          },
          {
            key: "max_tokens",
            label: "Max tokens",
            description: "Maximum output tokens",
            kind: "integer",
            minimum: 1,
            maximum: null,
          },
          {
            key: "timeout_seconds",
            label: "Model timeout",
            description: "Model request timeout",
            kind: "number",
            minimum: 0.001,
            maximum: null,
          },
          {
            key: "max_retries",
            label: "Model retries",
            description: "Model retry count",
            kind: "integer",
            minimum: 0,
            maximum: null,
          },
          {
            key: "retry_backoff_seconds",
            label: "Retry backoff",
            description: "Retry delay",
            kind: "number",
            minimum: 0,
            maximum: null,
          },
        ],
      },
      {
        key: "retrieval_settings",
        label: "Search",
        fields: [
          {
            key: "top_k",
            label: "Candidate count",
            description: "Candidate retrieval count",
            kind: "integer",
            minimum: 1,
            maximum: null,
          },
          {
            key: "rrf_k",
            label: "RRF K",
            description: "Fusion smoothing",
            kind: "integer",
            minimum: 0,
            maximum: null,
          },
          {
            key: "dense_weight",
            label: "Dense weight",
            description: "Dense ranking weight",
            kind: "number",
            minimum: 0,
            maximum: null,
          },
          {
            key: "keyword_weight",
            label: "Keyword weight",
            description: "Keyword ranking weight",
            kind: "number",
            minimum: 0,
            maximum: null,
          },
          {
            key: "rerank_top_k",
            label: "Rerank count",
            description: "Reranked result count",
            kind: "integer",
            minimum: 1,
            maximum: null,
          },
          {
            key: "context_max_chars",
            label: "Context size",
            description: "Maximum context characters",
            kind: "integer",
            minimum: 1,
            maximum: null,
          },
        ],
      },
      {
        key: "runtime_settings",
        label: "Runtime",
        fields: [
          {
            key: "max_steps",
            label: "Runtime max steps",
            description: "Maximum runtime steps",
            kind: "integer",
            minimum: 1,
            maximum: null,
          },
          {
            key: "tool_timeout_seconds",
            label: "Tool timeout",
            description: "Tool request timeout",
            kind: "number",
            minimum: 0.001,
            maximum: null,
          },
          {
            key: "logs_max_lines",
            label: "Log line limit",
            description: "Maximum log lines",
            kind: "integer",
            minimum: 1,
            maximum: null,
          },
          {
            key: "evidence_max_chars",
            label: "Evidence size",
            description: "Maximum evidence characters",
            kind: "integer",
            minimum: 1,
            maximum: null,
          },
        ],
      },
    ],
    configuration_rules: [
      {
        kind: "less_equal",
        group: "retrieval_settings",
        fields: ["rerank_top_k", "top_k"],
        target_field: "rerank_top_k",
        message: "Rerank count must not exceed candidate count.",
      },
      {
        kind: "not_all_zero",
        group: "retrieval_settings",
        fields: ["dense_weight", "keyword_weight"],
        target_field: "keyword_weight",
        message: "Retrieval weights cannot both be zero.",
      },
    ],
    default_enabled: true,
  };
}

function effectiveConfiguration(): EffectiveAgentConfiguration {
  return {
    agent_type: "docker_support",
    display_name: "Docker Support",
    enabled: true,
    persisted: false,
    configuration_updated_at: null,
    model_settings: {
      model_name: field("env-model"),
      temperature: field(0.1),
      max_tokens: field(null),
      timeout_seconds: field(60),
      max_retries: field(2),
      retry_backoff_seconds: field(0.5),
    },
    retrieval_settings: {
      top_k: field(20),
      rrf_k: field(60),
      dense_weight: field(1),
      keyword_weight: field(1),
      rerank_top_k: field(5),
      context_max_chars: field(14000),
    },
    runtime_settings: {
      max_steps: field(4),
      tool_timeout_seconds: field(15),
      logs_max_lines: field(200),
      evidence_max_chars: field(8000),
    },
    environment_settings: {},
  };
}

function persistedConfiguration(
  overrides: {
    displayName?: string;
    enabled?: boolean;
    temperature?: number;
    topK?: number;
  } = {},
): EffectiveAgentConfiguration {
  const config = effectiveConfiguration();
  config.persisted = true;
  config.configuration_updated_at = "2026-09-21T03:00:00Z";
  config.display_name = overrides.displayName ?? "Docker Support";
  config.enabled = overrides.enabled ?? true;

  if (overrides.temperature !== undefined) {
    config.model_settings.temperature = {
      ...field(0.1),
      persisted_value: overrides.temperature,
      effective_value: overrides.temperature,
      source: "persisted",
    };
  }

  if (overrides.topK !== undefined) {
    config.retrieval_settings.top_k = {
      ...field(20),
      persisted_value: overrides.topK,
      effective_value: overrides.topK,
      source: "persisted",
    };
  }

  return config;
}

function findField(
  settings: ReturnType<typeof useAgentSettings>,
  group:
    | "model_settings"
    | "retrieval_settings"
    | "runtime_settings",
  key: string,
) {
  const item = settings.fields.value[group].find(
    (candidate) => candidate.key === key,
  );
  if (!item) {
    throw new Error(`Missing field ${group}.${key}`);
  }
  return item;
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getAgentDescriptor).mockResolvedValue(agentDescriptor());
});

describe("editable agent settings", () => {
  it("loads configuration metadata for the requested Agent type", async () => {
    const descriptor = agentDescriptor();
    descriptor.agent_type = "future_agent";
    descriptor.display_name = "Future Agent";
    const effective = effectiveConfiguration();
    effective.agent_type = "future_agent";
    effective.display_name = "Future Agent";

    vi.mocked(getAgentDescriptor).mockResolvedValueOnce(descriptor);
    vi.mocked(getEffectiveAgentConfiguration).mockResolvedValueOnce(
      effective,
    );

    const settings = useAgentSettings("future_agent");
    await settings.load();

    expect(getAgentDescriptor).toHaveBeenCalledWith("future_agent");
    expect(getEffectiveAgentConfiguration).toHaveBeenCalledWith(
      "future_agent",
    );
    expect(settings.descriptor.value?.display_name).toBe("Future Agent");
    expect(settings.displayName.value).toBe("Future Agent");
  });

  it("hydrates field metadata from the Agent descriptor", async () => {
    vi.mocked(getEffectiveAgentConfiguration).mockResolvedValue(
      effectiveConfiguration(),
    );

    const settings = useAgentSettings();
    await settings.load();

    const temperature = findField(
      settings,
      "model_settings",
      "temperature",
    );
    expect(temperature.label).toBe("Sampling temperature");
    expect(temperature.minimum).toBe(0);
    expect(temperature.maximum).toBe(2);

    expect(
      settings.descriptor.value?.configuration_schema[1]?.label,
    ).toBe("Search");
  });

  it("creates the first persisted config with explicit overrides only", async () => {
    vi.mocked(getEffectiveAgentConfiguration)
      .mockResolvedValueOnce(effectiveConfiguration())
      .mockResolvedValueOnce(
        persistedConfiguration({
          displayName: "Docker Expert",
          enabled: false,
          temperature: 0.4,
        }),
      );
    vi.mocked(createAgentConfiguration).mockResolvedValue({
      agent_type: "docker_support",
      display_name: "Docker Expert",
      enabled: false,
      model_settings: { temperature: 0.4 },
      retrieval_settings: {},
      runtime_settings: {},
      created_at: "2026-09-21T03:00:00Z",
      updated_at: "2026-09-21T03:00:00Z",
    });

    const settings = useAgentSettings();
    await settings.load();

    settings.displayName.value = "Docker Expert";
    settings.enabled.value = false;
    const temperature = findField(
      settings,
      "model_settings",
      "temperature",
    );
    settings.setOverride(temperature, true);
    temperature.input = "0.4";

    expect(await settings.save()).toBe(true);
    expect(createAgentConfiguration).toHaveBeenCalledWith({
      agent_type: "docker_support",
      display_name: "Docker Expert",
      enabled: false,
      model_settings: { temperature: 0.4 },
      retrieval_settings: {},
      runtime_settings: {},
    });
    expect(updateAgentConfiguration).not.toHaveBeenCalled();
    expect(settings.persisted.value).toBe(true);
    expect(settings.dirty.value).toBe(false);
  });

  it("removes disabled overrides from replacement setting groups", async () => {
    vi.mocked(getEffectiveAgentConfiguration)
      .mockResolvedValueOnce(
        persistedConfiguration({
          temperature: 0.3,
          topK: 12,
        }),
      )
      .mockResolvedValueOnce(
        persistedConfiguration({
          temperature: 0.3,
        }),
      );
    vi.mocked(updateAgentConfiguration).mockResolvedValue({
      agent_type: "docker_support",
      display_name: "Docker Support",
      enabled: true,
      model_settings: { temperature: 0.3 },
      retrieval_settings: {},
      runtime_settings: {},
      created_at: "2026-09-21T03:00:00Z",
      updated_at: "2026-09-21T03:01:00Z",
    });

    const settings = useAgentSettings();
    await settings.load();

    const topK = findField(
      settings,
      "retrieval_settings",
      "top_k",
    );
    expect(topK.override).toBe(true);
    settings.setOverride(topK, false);

    expect(await settings.save()).toBe(true);
    expect(updateAgentConfiguration).toHaveBeenCalledWith(
      "docker_support",
      {
        display_name: "Docker Support",
        enabled: true,
        model_settings: { temperature: 0.3 },
        retrieval_settings: {},
        runtime_settings: {},
      },
    );
  });

  it("applies descriptor cross-field ordering rules before saving", async () => {
    vi.mocked(getEffectiveAgentConfiguration).mockResolvedValue(
      effectiveConfiguration(),
    );

    const settings = useAgentSettings();
    await settings.load();

    const topK = findField(
      settings,
      "retrieval_settings",
      "top_k",
    );
    settings.setOverride(topK, true);
    topK.input = "3";

    expect(await settings.save()).toBe(false);
    expect(createAgentConfiguration).not.toHaveBeenCalled();
    expect(updateAgentConfiguration).not.toHaveBeenCalled();

    const rerankTopK = findField(
      settings,
      "retrieval_settings",
      "rerank_top_k",
    );
    expect(rerankTopK.error).toBe(
      "Rerank count must not exceed candidate count.",
    );
  });

  it("applies descriptor not-all-zero rules before saving", async () => {
    vi.mocked(getEffectiveAgentConfiguration).mockResolvedValue(
      effectiveConfiguration(),
    );

    const settings = useAgentSettings();
    await settings.load();

    const dense = findField(
      settings,
      "retrieval_settings",
      "dense_weight",
    );
    const keyword = findField(
      settings,
      "retrieval_settings",
      "keyword_weight",
    );
    settings.setOverride(dense, true);
    settings.setOverride(keyword, true);
    dense.input = "0";
    keyword.input = "0";

    expect(await settings.save()).toBe(false);
    expect(keyword.error).toBe(
      "Retrieval weights cannot both be zero.",
    );
    expect(createAgentConfiguration).not.toHaveBeenCalled();
  });
});
