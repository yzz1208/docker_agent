import type {
  AgentConfiguration,
  AgentConfigurationCreate,
  AgentConfigurationMutation,
  ChatResponse,
  ConversationDetail,
  ConversationSummary,
  EffectiveAgentConfiguration,
} from "./types";

type JsonBody = Record<string, unknown>;

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

function jsonBody(body: JsonBody): string {
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
  conversationId?: string | null;
  sessionId?: string | null;
}): Promise<ChatResponse> {
  return request<ChatResponse>("/chat", {
    method: "POST",
    body: jsonBody({
      message: input.message,
      conversation_id: input.conversationId ?? null,
      session_id: input.sessionId ?? null,
    }),
  });
}

export function resetChatSession(
  sessionId: string,
): Promise<void> {
  return request<void>(
    `/chat/${encodeURIComponent(sessionId)}`,
    { method: "DELETE" },
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
