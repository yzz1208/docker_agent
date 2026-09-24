import type {
  AgentConfiguration,
  AgentConfigurationCreate,
  AutoChatProgressEvent,
  AutoChatResponse,
  AgentDescriptor,
  AgentConfigurationMutation,
  AgentRunRecord,
  AgentRunStatus,
  AgentRunSummary,
  ChatResponse,
  ConversationDetail,
  ConversationSummary,
  DatabaseHealth,
  EffectiveAgentConfiguration,
  EvaluationComparison,
  EvaluationRun,
  EvaluationRunDetail,
  SystemHealth,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(path, {
    ...init,
    headers,
  });

  if (!response.ok) {
    let detail = response.statusText || "Request failed.";
    try {
      const payload = (await response.json()) as {
        detail?: unknown;
      };
      if (typeof payload.detail === "string") {
        detail = payload.detail;
      }
    } catch {
      // Keep the HTTP status text when the backend has no JSON body.
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

function jsonBody(body: unknown): string {
  return JSON.stringify(body);
}

export function listConversations(
  limit = 50,
  offset = 0,
): Promise<ConversationSummary[]> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  return request<ConversationSummary[]>(
    `/conversations?${params.toString()}`,
  );
}

export function getConversation(
  conversationId: string,
): Promise<ConversationDetail> {
  return request<ConversationDetail>(
    `/conversations/${encodeURIComponent(conversationId)}`,
  );
}

export function renameConversation(
  conversationId: string,
  title: string,
): Promise<ConversationSummary> {
  return request<ConversationSummary>(
    `/conversations/${encodeURIComponent(conversationId)}`,
    {
      method: "PATCH",
      body: jsonBody({ title }),
    },
  );
}

export function deleteConversation(
  conversationId: string,
): Promise<void> {
  return request<void>(
    `/conversations/${encodeURIComponent(conversationId)}`,
    { method: "DELETE" },
  );
}

export function sendChat(input: {
  message: string;
  agentType?: string | null;
  conversationId?: string | null;
  sessionId?: string | null;
}): Promise<ChatResponse> {
  return request<ChatResponse>("/chat", {
    method: "POST",
    body: jsonBody({
      message: input.message,
      agent_type: input.agentType ?? null,
      conversation_id: input.conversationId ?? null,
      session_id: input.sessionId ?? null,
    }),
  });
}

export function sendAutoChat(input: {
  message: string;
  conversationId?: string | null;
}): Promise<AutoChatResponse> {
  return request<AutoChatResponse>("/chat/auto", {
    method: "POST",
    body: jsonBody({
      message: input.message,
      conversation_id: input.conversationId ?? null,
    }),
  });
}


type ParsedSseEvent = {
  event: string;
  data: unknown;
};

function parseSseEvent(block: string): ParsedSseEvent | null {
  let event = "message";
  const dataLines: string[] = [];

  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trimStart());
    }
  }

  if (!dataLines.length) return null;

  try {
    return {
      event,
      data: JSON.parse(dataLines.join("\n")) as unknown,
    };
  } catch {
    throw new ApiError(
      502,
      "服务端返回了无法解析的流式事件。",
    );
  }
}

async function streamHttpError(
  response: Response,
): Promise<ApiError> {
  let detail = response.statusText || "Request failed.";
  try {
    const payload = (await response.json()) as {
      detail?: unknown;
    };
    if (typeof payload.detail === "string") {
      detail = payload.detail;
    }
  } catch {
    // Keep the HTTP status text when the backend has no JSON body.
  }
  return new ApiError(response.status, detail);
}

export async function sendAutoChatStream(
  input: {
    message: string;
    conversationId?: string | null;
  },
  onProgress?: (event: AutoChatProgressEvent) => void,
  onDelta?: (delta: string) => void,
): Promise<AutoChatResponse> {
  const response = await fetch("/chat/auto/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: jsonBody({
      message: input.message,
      conversation_id: input.conversationId ?? null,
    }),
  });

  if (!response.ok) {
    throw await streamHttpError(response);
  }
  if (!response.body) {
    throw new ApiError(
      502,
      "浏览器没有收到流式响应内容。",
    );
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult: AutoChatResponse | null = null;

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });

    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseSseEvent(block);

      if (parsed?.event === "progress") {
        const payload = parsed.data as Partial<AutoChatProgressEvent>;
        if (
          typeof payload.stage === "string" &&
          (payload.status === "started" ||
            payload.status === "completed")
        ) {
          onProgress?.({
            stage: payload.stage,
            status: payload.status,
            duration_ms:
              typeof payload.duration_ms === "number"
                ? payload.duration_ms
                : null,
          });
        }
      } else if (parsed?.event === "delta") {
        const payload = parsed.data as {
          text?: unknown;
        };
        if (typeof payload.text === "string" && payload.text) {
          onDelta?.(payload.text);
        }
      } else if (parsed?.event === "result") {
        finalResult = parsed.data as AutoChatResponse;
      } else if (parsed?.event === "error") {
        const payload = parsed.data as {
          message?: unknown;
        };
        throw new ApiError(
          502,
          typeof payload.message === "string"
            ? payload.message
            : "智能编排执行失败，请稍后重试。",
        );
      }

      boundary = buffer.indexOf("\n\n");
    }

    if (done) break;
  }

  if (!finalResult) {
    throw new ApiError(
      502,
      "流式响应结束，但没有收到最终回答。",
    );
  }
  return finalResult;
}

export function getAutoApproval(
  conversationId: string,
): Promise<AutoChatResponse | null> {
  return request<AutoChatResponse | null>(
    `/chat/auto/${encodeURIComponent(conversationId)}/approval`,
  );
}

export function resolveAutoApproval(input: {
  conversationId: string;
  approved: boolean;
  comment?: string | null;
}): Promise<AutoChatResponse> {
  return request<AutoChatResponse>(
    `/chat/auto/${encodeURIComponent(input.conversationId)}/approval`,
    {
      method: "POST",
      body: jsonBody({
        approved: input.approved,
        comment: input.comment ?? null,
      }),
    },
  );
}

export function resetChatSession(
  sessionId: string,
  agentType?: string | null,
): Promise<void> {
  const params = new URLSearchParams();
  if (agentType) {
    params.set("agent_type", agentType);
  }
  const query = params.toString();

  return request<void>(
    `/chat/${encodeURIComponent(sessionId)}${query ? `?${query}` : ""}`,
    { method: "DELETE" },
  );
}

export function listAgents(): Promise<AgentDescriptor[]> {
  return request<AgentDescriptor[]>("/agents");
}

export function getAgentDescriptor(
  agentType: string,
): Promise<AgentDescriptor> {
  return request<AgentDescriptor>(
    `/agents/${encodeURIComponent(agentType)}`,
  );
}

export function getAgentConfiguration(
  agentType: string,
): Promise<AgentConfiguration> {
  return request<AgentConfiguration>(
    `/agent-configurations/${encodeURIComponent(agentType)}`,
  );
}

export function getEffectiveAgentConfiguration(
  agentType: string,
): Promise<EffectiveAgentConfiguration> {
  return request<EffectiveAgentConfiguration>(
    `/agent-configurations/${encodeURIComponent(agentType)}/effective`,
  );
}

export function createAgentConfiguration(
  body: AgentConfigurationCreate,
): Promise<AgentConfiguration> {
  return request<AgentConfiguration>("/agent-configurations", {
    method: "POST",
    body: jsonBody(body),
  });
}

export function updateAgentConfiguration(
  agentType: string,
  body: AgentConfigurationMutation,
): Promise<AgentConfiguration> {
  return request<AgentConfiguration>(
    `/agent-configurations/${encodeURIComponent(agentType)}`,
    {
      method: "PATCH",
      body: jsonBody(body),
    },
  );
}


export function getSystemHealth(): Promise<SystemHealth> {
  return request<SystemHealth>("/health");
}

export function getDatabaseHealth(): Promise<DatabaseHealth> {
  return request<DatabaseHealth>("/health/db");
}


export function listAgentRuns(input: {
  conversationId?: string;
  agentType?: string;
  status?: AgentRunStatus;
  limit?: number;
  offset?: number;
} = {}): Promise<AgentRunRecord[]> {
  const params = new URLSearchParams();
  if (input.conversationId) {
    params.set("conversation_id", input.conversationId);
  }
  if (input.agentType) {
    params.set("agent_type", input.agentType);
  }
  if (input.status) {
    params.set("status", input.status);
  }
  params.set("limit", String(input.limit ?? 50));
  params.set("offset", String(input.offset ?? 0));

  return request<AgentRunRecord[]>(
    `/operations/runs?${params.toString()}`,
  );
}

export function getAgentRun(
  runId: string,
): Promise<AgentRunRecord> {
  return request<AgentRunRecord>(
    `/operations/runs/${encodeURIComponent(runId)}`,
  );
}

export function getOperationsSummary(
  hours = 24,
  agentType?: string,
): Promise<AgentRunSummary> {
  const params = new URLSearchParams({
    hours: String(hours),
  });
  if (agentType) {
    params.set("agent_type", agentType);
  }
  return request<AgentRunSummary>(
    `/operations/summary?${params.toString()}`,
  );
}

export function listEvaluationRuns(input: {
  suite?: string;
  agentType?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<EvaluationRun[]> {
  const params = new URLSearchParams({
    limit: String(input.limit ?? 50),
    offset: String(input.offset ?? 0),
  });
  if (input.suite) {
    params.set("suite", input.suite);
  }
  if (input.agentType) {
    params.set("agent_type", input.agentType);
  }

  return request<EvaluationRun[]>(
    `/operations/evaluations?${params.toString()}`,
  );
}

export function getEvaluationRun(
  runId: string,
): Promise<EvaluationRunDetail> {
  return request<EvaluationRunDetail>(
    `/operations/evaluations/${encodeURIComponent(runId)}`,
  );
}

export function compareEvaluationRuns(input: {
  baselineId: string;
  candidateId: string;
  maxRegression?: number;
}): Promise<EvaluationComparison> {
  const params = new URLSearchParams({
    baseline_id: input.baselineId,
    candidate_id: input.candidateId,
    max_regression: String(input.maxRegression ?? 0.02),
  });

  return request<EvaluationComparison>(
    `/operations/evaluations/compare?${params.toString()}`,
  );
}
