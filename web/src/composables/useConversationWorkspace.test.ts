import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AgentDescriptor,
  AutoChatResponse,
  ChatResponse,
  ConversationDetail,
  ConversationSummary,
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
  deleteConversation: vi.fn(),
  getAutoApproval: vi.fn(),
  getConversation: vi.fn(),
  listAgents: vi.fn(),
  listConversations: vi.fn(),
  renameConversation: vi.fn(),
  resolveAutoApproval: vi.fn(),
  sendAutoChat: vi.fn(),
  sendChat: vi.fn(),
}));

import {
  deleteConversation,
  getAutoApproval,
  getConversation,
  listAgents,
  listConversations,
  renameConversation,
  resolveAutoApproval,
  sendAutoChat,
  sendChat,
} from "../lib/api";
import { useConversationWorkspace } from "./useConversationWorkspace";

const agents: AgentDescriptor[] = [
  {
    agent_type: "docker_support",
    display_name: "Docker Support",
    description: "Docker troubleshooting Agent.",
    capabilities: ["chat", "docker_troubleshooting"],
    knowledge_sources: ["docker_docs"],
    toolsets: ["docker_read_only"],
    worker_roles: ["runtime", "diagnosis"],
    configuration_groups: [],
    configuration_schema: [],
    configuration_rules: [],
    default_enabled: true,
  },
  {
    agent_type: "infrastructure_troubleshooter",
    display_name: "Infrastructure Troubleshooter",
    description: "Infrastructure incident triage Agent.",
    capabilities: ["chat", "incident_triage"],
    knowledge_sources: [],
    toolsets: [],
    worker_roles: ["triage", "diagnosis"],
    configuration_groups: [],
    configuration_schema: [],
    configuration_rules: [],
    default_enabled: true,
  },
];

const conversation: ConversationSummary = {
  id: "conversation-1",
  agent_type: "docker_support",
  title: "Docker issue",
  created_at: "2026-09-21T00:00:00Z",
  updated_at: "2026-09-21T00:00:01Z",
};

function detailFor(
  id: string,
  title = "Docker issue",
  agentType = "docker_support",
): ConversationDetail {
  return {
    conversation: {
      ...conversation,
      id,
      title,
      agent_type: agentType,
    },
    messages: [],
  };
}

function autoTurn(
  overrides: Partial<AutoChatResponse> = {},
): AutoChatResponse {
  return {
    mode: "auto",
    conversation_id: "auto-conversation",
    current_agent_type: "docker_support",
    route: "auto_direct",
    answer: "容器运行正常。",
    clarification: null,
    needs_clarification: false,
    synthesized: false,
    trace: [
      {
        stage: "decision",
        label: "智能判断",
        agent_type: "docker_support",
        capability: "runtime_diagnostics",
        reason: "需要运行时诊断",
      },
      {
        stage: "specialist",
        label: "专家处理",
        agent_type: "docker_support",
        capability: "runtime_diagnostics",
        reason: "需要运行时诊断",
      },
    ],
    approval_status: null,
    needs_approval: false,
    approval_request: null,
    specialist_results: [
      {
        agent_type: "docker_support",
        route: "runtime_tools",
        reason: "runtime checked",
        needs_clarification: false,
        clarification: null,
        summary: "容器运行正常。",
      },
    ],
    ...overrides,
  };
}


function chatTurn(
  overrides: Partial<ChatResponse> = {},
): ChatResponse {
  return {
    agent_type: "docker_support",
    conversation_id: "conversation-1",
    session_id: "session-1",
    session_active: false,
    route: "runtime_only",
    reason: "Runtime evidence required.",
    use_docs: false,
    clarification: null,
    answer: "Done",
    runtime_sources: [],
    doc_sources: [],
    execution: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(listAgents).mockResolvedValue(agents);
  vi.mocked(listConversations).mockResolvedValue([conversation]);
  vi.mocked(getConversation).mockResolvedValue(
    detailFor("conversation-1"),
  );
  vi.mocked(getAutoApproval).mockResolvedValue(null);
  vi.mocked(renameConversation).mockResolvedValue(conversation);
  vi.mocked(deleteConversation).mockResolvedValue(undefined);
  vi.mocked(resolveAutoApproval).mockResolvedValue(autoTurn());
});

describe("conversation workspace", () => {
  it("keeps an active clarification session for the next turn", async () => {
    vi.mocked(sendChat).mockResolvedValue(
      chatTurn({
        session_active: true,
        clarification: "Which container?",
        answer: null,
      }),
    );

    const workspace = useConversationWorkspace();
    workspace.draft.value = "The container stopped";

    expect(await workspace.submitMessage()).toBe(true);
    expect(workspace.activeConversationId.value).toBe(
      "conversation-1",
    );
    expect(workspace.activeSessionId.value).toBe("session-1");

    vi.mocked(sendChat).mockResolvedValue(
      chatTurn({
        session_id: "session-1",
        session_active: false,
      }),
    );
    workspace.draft.value = "container api-1";

    expect(await workspace.submitMessage()).toBe(true);
    expect(sendChat).toHaveBeenLastCalledWith({
      message: "container api-1",
      agentType: "docker_support",
      conversationId: "conversation-1",
      sessionId: "session-1",
    });
    expect(workspace.activeSessionId.value).toBeNull();
  });

  it("allows another message after a completed turn", async () => {
    vi.mocked(sendChat)
      .mockResolvedValueOnce(
        chatTurn({
          answer: "第一轮完成",
          session_active: false,
        }),
      )
      .mockResolvedValueOnce(
        chatTurn({
          answer: "第二轮完成",
          session_active: false,
        }),
      );
    vi.mocked(getConversation).mockResolvedValue(
      detailFor("conversation-1"),
    );

    const workspace = useConversationWorkspace();
    workspace.draft.value = "第一条问题";

    expect(await workspace.submitMessage()).toBe(true);
    expect(workspace.sending.value).toBe(false);

    workspace.draft.value = "继续追问";
    expect(workspace.canSend.value).toBe(true);
    expect(await workspace.submitMessage()).toBe(true);

    expect(sendChat).toHaveBeenCalledTimes(2);
    expect(sendChat).toHaveBeenLastCalledWith({
      message: "继续追问",
      agentType: undefined,
      conversationId: "conversation-1",
      sessionId: null,
    });
    expect(workspace.sending.value).toBe(false);
  });

  it("keeps a completed answer visible when history refresh fails", async () => {
    vi.mocked(sendChat).mockResolvedValue(
      chatTurn({
        answer: "回答已经完成",
        session_active: false,
      }),
    );
    vi.mocked(getConversation).mockRejectedValueOnce(
      new Error("temporary refresh failure"),
    );

    const workspace = useConversationWorkspace();
    workspace.draft.value = "检查 Docker";

    expect(await workspace.submitMessage()).toBe(true);
    expect(workspace.transientAssistantMessage.value).toBe(
      "回答已经完成",
    );
    expect(workspace.sending.value).toBe(false);
    expect(workspace.actionError.value).toContain(
      "回答已经生成",
    );

    workspace.draft.value = "继续追问";
    expect(workspace.canSend.value).toBe(true);
  });

  it("uses the selected Agent when starting a new conversation", async () => {
    vi.mocked(sendChat).mockResolvedValue(
      chatTurn({
        agent_type: "infrastructure_troubleshooter",
        conversation_id: "conversation-infra",
        session_id: "session-infra",
        route: "triage",
      }),
    );
    vi.mocked(getConversation).mockResolvedValueOnce(
      detailFor(
        "conversation-infra",
        "API latency incident",
        "infrastructure_troubleshooter",
      ),
    );

    const workspace = useConversationWorkspace();
    await workspace.refreshAgents();
    workspace.selectedAgentType.value =
      "infrastructure_troubleshooter";
    workspace.draft.value = "checkout-api is returning 503";

    expect(await workspace.submitMessage()).toBe(true);
    expect(sendChat).toHaveBeenCalledWith({
      message: "checkout-api is returning 503",
      agentType: "infrastructure_troubleshooter",
      conversationId: null,
      sessionId: null,
    });
    expect(workspace.activeAgentType.value).toBe(
      "infrastructure_troubleshooter",
    );
    expect(workspace.activeAgent.value?.display_name).toBe(
      "Infrastructure Troubleshooter",
    );
  });

  it("preserves latest-turn details while navigating conversations", async () => {
    vi.mocked(sendChat).mockResolvedValue(chatTurn());
    vi.mocked(getConversation)
      .mockResolvedValueOnce(detailFor("conversation-1"))
      .mockResolvedValueOnce(detailFor("conversation-2", "Other issue"))
      .mockResolvedValueOnce(detailFor("conversation-1"));

    const workspace = useConversationWorkspace();
    workspace.draft.value = "Inspect Docker";

    await workspace.submitMessage();
    expect(workspace.latestTurn.value?.reason).toBe(
      "Runtime evidence required.",
    );

    await workspace.openConversation("conversation-2");
    expect(workspace.latestTurn.value).toBeNull();

    await workspace.openConversation("conversation-1");
    expect(workspace.latestTurn.value?.reason).toBe(
      "Runtime evidence required.",
    );
  });

  it("ignores stale conversation responses", async () => {
    let resolveFirst:
      | ((value: ConversationDetail) => void)
      | undefined;
    const first = new Promise<ConversationDetail>((resolve) => {
      resolveFirst = resolve;
    });

    vi.mocked(getConversation)
      .mockReturnValueOnce(first)
      .mockResolvedValueOnce(
        detailFor("conversation-2", "Second conversation"),
      );

    const workspace = useConversationWorkspace();
    const firstRequest = workspace.openConversation("conversation-1");
    await workspace.openConversation("conversation-2");

    resolveFirst?.(detailFor("conversation-1"));
    await firstRequest;

    expect(workspace.activeConversationId.value).toBe(
      "conversation-2",
    );
    expect(workspace.detail.value?.conversation.id).toBe(
      "conversation-2",
    );
  });

  it("uses auto orchestration mode without calling manual chat", async () => {
    vi.mocked(sendAutoChat).mockResolvedValue(autoTurn());
    vi.mocked(getConversation).mockResolvedValueOnce(
      detailFor(
        "auto-conversation",
        "Auto issue",
        "auto_orchestration",
      ),
    );

    const workspace = useConversationWorkspace();
    workspace.selectedMode.value = "auto";
    workspace.draft.value = "容器正常，但服务仍然 503";

    expect(await workspace.submitMessage()).toBe(true);
    expect(sendAutoChat).toHaveBeenCalledWith({
      message: "容器正常，但服务仍然 503",
      conversationId: null,
    });
    expect(sendChat).not.toHaveBeenCalled();
    expect(workspace.activeMode.value).toBe("auto");
    expect(workspace.latestAutoTurn.value?.current_agent_type).toBe(
      "docker_support",
    );
    expect(workspace.agentDisplayName("docker_support")).toBe(
      "Docker 支持",
    );
  });

  it("locks sending while auto approval is pending and resolves it", async () => {
    const pending = autoTurn({
      route: "auto_approval_pending",
      answer: null,
      current_agent_type: "docker_support",
      approval_status: "pending",
      needs_approval: true,
      approval_request: {
        interrupt_id: "interrupt-1",
        action: "delegate",
        source_agent_type: "docker_support",
        target_agent_type: "infrastructure_troubleshooter",
        capability: "incident_triage",
        reason: "需要服务级排查",
        question: "继续排查 checkout-api 503",
        response_schema: {},
      },
    });
    const completed = autoTurn({
      route: "auto_synthesis",
      current_agent_type: "infrastructure_troubleshooter",
      answer: "服务级排查完成。",
      synthesized: true,
      approval_status: "approved",
      needs_approval: false,
      approval_request: null,
    });
    vi.mocked(sendAutoChat).mockResolvedValue(pending);
    vi.mocked(resolveAutoApproval).mockResolvedValue(completed);
    vi.mocked(getConversation).mockResolvedValue(
      detailFor(
        "auto-conversation",
        "Auto issue",
        "auto_orchestration",
      ),
    );

    const workspace = useConversationWorkspace();
    workspace.selectedMode.value = "auto";
    workspace.draft.value = "继续排查 checkout-api 503";

    expect(await workspace.submitMessage()).toBe(true);
    expect(workspace.pendingApproval.value?.capability).toBe(
      "incident_triage",
    );
    workspace.draft.value = "不应该现在发送";
    expect(workspace.canSend.value).toBe(false);

    expect(
      await workspace.resolvePendingApproval(true),
    ).toBe(true);
    expect(resolveAutoApproval).toHaveBeenCalledWith({
      conversationId: "auto-conversation",
      approved: true,
      comment: "用户批准继续执行。",
    });
    expect(workspace.pendingApproval.value).toBeNull();
    expect(workspace.latestAutoTurn.value?.synthesized).toBe(true);
  });

  it("recovers pending auto approval when reopening history", async () => {
    const autoDetail = detailFor(
      "auto-conversation",
      "Auto issue",
      "auto_orchestration",
    );
    const pending = autoTurn({
      route: "auto_approval_pending",
      answer: null,
      approval_status: "pending",
      needs_approval: true,
      approval_request: {
        interrupt_id: "interrupt-1",
        action: "delegate",
        source_agent_type: "docker_support",
        target_agent_type: "infrastructure_troubleshooter",
        capability: "incident_triage",
        reason: "需要服务级排查",
        question: "继续排查 checkout-api 503",
        response_schema: {},
      },
    });
    vi.mocked(getConversation).mockResolvedValueOnce(autoDetail);
    vi.mocked(getAutoApproval).mockResolvedValueOnce(pending);

    const workspace = useConversationWorkspace();
    await workspace.openConversation("auto-conversation");

    expect(getAutoApproval).toHaveBeenCalledWith(
      "auto-conversation",
    );
    expect(workspace.pendingApproval.value?.target_agent_type).toBe(
      "infrastructure_troubleshooter",
    );
    expect(workspace.canSend.value).toBe(false);
  });

  it("restores persisted auto trace when opening history", async () => {
    const autoDetail: ConversationDetail = {
      conversation: {
        ...conversation,
        id: "auto-conversation",
        agent_type: "auto_orchestration",
        title: "Auto issue",
      },
      messages: [
        {
          id: "assistant-auto",
          role: "assistant",
          content: "容器运行正常。",
          route: "auto_direct",
          use_docs: null,
          clarification: null,
          created_at: "2026-09-21T00:00:02Z",
          execution: {
            id: "exec-auto",
            planned_workers: ["docker_support"],
            completed_workers: ["docker_support"],
            worker_trace: [
              {
                kind: "orchestration_trace",
                stage: "specialist",
                label: "专家处理",
                agent_type: "docker_support",
                capability: "runtime_diagnostics",
                reason: "runtime",
              },
              {
                kind: "auto_state",
                current_agent_type: "docker_support",
              },
            ],
            created_at: "2026-09-21T00:00:02Z",
          },
        },
      ],
    };
    vi.mocked(getConversation).mockResolvedValueOnce(autoDetail);

    const workspace = useConversationWorkspace();
    await workspace.openConversation("auto-conversation");

    expect(workspace.activeMode.value).toBe("auto");
    expect(workspace.latestAutoTurn.value?.current_agent_type).toBe(
      "docker_support",
    );
    expect(workspace.latestAutoTurn.value?.trace[0]?.stage).toBe(
      "specialist",
    );
  });

  it("updates local state after rename and delete", async () => {
    const renamed = {
      ...conversation,
      title: "Renamed issue",
    };
    vi.mocked(renameConversation).mockResolvedValue(renamed);

    const workspace = useConversationWorkspace();
    workspace.conversations.value = [conversation];
    workspace.detail.value = detailFor("conversation-1");
    workspace.activeConversationId.value = "conversation-1";

    expect(
      await workspace.renameActiveConversation(" Renamed issue "),
    ).toBe(true);
    expect(workspace.detail.value?.conversation.title).toBe(
      "Renamed issue",
    );
    expect(workspace.conversations.value[0]?.title).toBe(
      "Renamed issue",
    );

    expect(await workspace.deleteActiveConversation()).toBe(true);
    expect(workspace.conversations.value).toEqual([]);
    expect(workspace.activeConversationId.value).toBeNull();
    expect(workspace.detail.value).toBeNull();
  });
});
