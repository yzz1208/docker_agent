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
