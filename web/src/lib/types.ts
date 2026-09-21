export type WorkerExecution = {
  index: number;
  role: string;
  tool_results_added: number;
  evidence_added: number;
  runtime_steps_added: number;
  answer_created: boolean;
};

export type AgentExecution = {
  planned_workers: string[];
  completed_workers: string[];
  worker_trace: WorkerExecution[];
};

export type RuntimeSource = {
  index: number;
  tool: string;
  command: string[];
  ok: boolean;
};

export type DocSource = {
  index: number;
  title: string;
  section: string;
  source_url: string;
};

export type ChatResponse = {
  agent_type: string;
  conversation_id: string | null;
  session_id: string;
  session_active: boolean;
  route: string;
  reason: string;
  use_docs: boolean;
  clarification: string | null;
  answer: string | null;
  runtime_sources: RuntimeSource[];
  doc_sources: DocSource[];
  execution: AgentExecution | null;
};

export type ConversationSummary = {
  id: string;
  agent_type: string;
  title: string | null;
  created_at: string;
  updated_at: string;
};

export type ConversationExecution = {
  id: string;
  planned_workers: string[];
  completed_workers: string[];
  worker_trace: Record<string, unknown>[];
  created_at: string;
};

export type ConversationMessage = {
  id: string;
  role: string;
  content: string;
  route: string | null;
  use_docs: boolean | null;
  clarification: string | null;
  created_at: string;
  execution: ConversationExecution | null;
};

export type ConversationDetail = {
  conversation: ConversationSummary;
  messages: ConversationMessage[];
};

export type AgentConfiguration = {
  agent_type: string;
  display_name: string;
  enabled: boolean;
  model_settings: Record<string, unknown>;
  retrieval_settings: Record<string, unknown>;
  runtime_settings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ConfigurationSource =
  | "persisted"
  | "environment"
  | "default";

export type ConfigurationScalar =
  | string
  | number
  | boolean
  | null;

export type EffectiveConfigurationField = {
  persisted_value: ConfigurationScalar;
  base_value: ConfigurationScalar;
  effective_value: ConfigurationScalar;
  source: ConfigurationSource;
  editable: boolean;
  secure: boolean;
  configured: boolean;
};

export type EffectiveAgentConfiguration = {
  agent_type: string;
  display_name: string;
  enabled: boolean;
  persisted: boolean;
  configuration_updated_at: string | null;
  model_settings: Record<string, EffectiveConfigurationField>;
  retrieval_settings: Record<string, EffectiveConfigurationField>;
  runtime_settings: Record<string, EffectiveConfigurationField>;
  environment_settings: Record<string, EffectiveConfigurationField>;
};


export type AgentConfigurationMutation = {
  display_name?: string;
  enabled?: boolean;
  model_settings?: Record<string, unknown>;
  retrieval_settings?: Record<string, unknown>;
  runtime_settings?: Record<string, unknown>;
};

export type AgentConfigurationCreate = AgentConfigurationMutation & {
  agent_type: string;
  display_name: string;
};


export type SystemHealth = {
  status: string;
  app: string;
  env: string;
};

export type DatabaseHealth = {
  status: string;
  database: string;
  detail?: string;
};


export type AgentRunStatus = "running" | "succeeded" | "failed";

export type AgentRunRecord = {
  id: string;
  conversation_id: string;
  agent_type: string;
  status: AgentRunStatus;
  route: string | null;
  use_docs: boolean | null;
  planned_workers: string[];
  completed_workers: string[];
  duration_ms: number | null;
  error_type: string | null;
  error_message: string | null;
  started_at: string;
  completed_at: string | null;
};

export type AgentRunSummary = {
  window_started_at: string;
  window_ended_at: string;
  total_runs: number;
  running_runs: number;
  succeeded_runs: number;
  failed_runs: number;
  success_rate: number | null;
  failure_rate: number | null;
  duration_p50_ms: number | null;
  duration_p95_ms: number | null;
  route_distribution: Record<string, number>;
  worker_distribution: Record<string, number>;
  error_distribution: Record<string, number>;
};

export type EvaluationRun = {
  id: string;
  suite: string;
  dataset_name: string;
  dataset_version: string;
  git_revision: string | null;
  status: "running" | "succeeded" | "failed";
  config_snapshot: Record<string, unknown>;
  aggregate_metrics: Record<string, unknown>;
  case_count: number;
  passed_count: number;
  failed_count: number;
  error_type: string | null;
  error_message: string | null;
  started_at: string;
  completed_at: string | null;
};

export type EvaluationCase = {
  id: string;
  evaluation_run_id: string;
  case_key: string;
  case_id: string;
  phase: string | null;
  repeat: number | null;
  status: "passed" | "failed" | "error";
  metrics: Record<string, unknown>;
  details: Record<string, unknown>;
  created_at: string;
};

export type EvaluationRunDetail = {
  run: EvaluationRun;
  cases: EvaluationCase[];
};

export type MetricComparison = {
  path: string;
  baseline_value: number;
  candidate_value: number;
  delta: number;
  quality_delta: number;
  direction: string;
  threshold: number;
  regression: boolean;
  improvement: boolean;
};

export type BehaviorChange = {
  case_key: string;
  field: string;
  baseline_value: unknown;
  candidate_value: unknown;
};

export type ConfigurationChange = {
  path: string;
  baseline_value: unknown;
  candidate_value: unknown;
};

export type EvaluationComparison = {
  baseline_run_id: string;
  candidate_run_id: string;
  suite: string;
  dataset_name: string;
  dataset_version: string;
  max_regression: number;
  verdict: "pass" | "regression" | "incomplete";
  gate_passed: boolean;
  common_case_count: number;
  baseline_only_case_keys: string[];
  candidate_only_case_keys: string[];
  new_failures: string[];
  new_passes: string[];
  unchanged_failures: string[];
  metric_comparisons: MetricComparison[];
  behavior_changes: BehaviorChange[];
  configuration_changes: ConfigurationChange[];
};


export type ConfigurationValueKind =
  | "string"
  | "integer"
  | "number";

export type ConfigurationFieldDescriptor = {
  key: string;
  label: string;
  description: string;
  kind: ConfigurationValueKind;
  minimum: number | null;
  maximum: number | null;
};

export type ConfigurationGroupDescriptor = {
  key: string;
  label: string;
  fields: ConfigurationFieldDescriptor[];
};

export type ConfigurationRuleDescriptor = {
  kind: "less_equal" | "not_all_zero";
  group: string;
  fields: string[];
  target_field: string;
  message: string;
};

export type AgentDescriptor = {
  agent_type: string;
  display_name: string;
  description: string;
  capabilities: string[];
  knowledge_sources: string[];
  toolsets: string[];
  worker_roles: string[];
  configuration_groups: string[];
  configuration_schema: ConfigurationGroupDescriptor[];
  configuration_rules: ConfigurationRuleDescriptor[];
  default_enabled: boolean;
};
