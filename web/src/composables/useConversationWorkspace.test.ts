import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
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
  getConversation: vi.fn(),
  listConversations: vi.fn(),
  renameConversation: vi.fn(),
  sendChat: vi.fn(),
}));

import {
  deleteConversation,
  getConversation,
  listConversations,
  renameConversation,
  sendChat,
} from "../lib/api";
import { useConversationWorkspace } from "./useConversationWorkspace";

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
): ConversationDetail {
  return {
    conversation: {
      ...conversation,
      id,
      title,
    },
    messages: [],
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
  vi.mocked(listConversations).mockResolvedValue([conversation]);
  vi.mocked(getConversation).mockResolvedValue(
    detailFor("conversation-1"),
  );
  vi.mocked(renameConversation).mockResolvedValue(conversation);
  vi.mocked(deleteConversation).mockResolvedValue(undefined);
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
      conversationId: "conversation-1",
      sessionId: "session-1",
    });
    expect(workspace.activeSessionId.value).toBeNull();
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
