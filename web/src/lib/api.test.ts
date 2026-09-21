import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, sendChat } from "./api";

describe("API client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("serializes durable and clarification identities", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          conversation_id: "conversation-1",
          session_id: "session-1",
          session_active: true,
          route: "clarify",
          reason: "Need more context",
          use_docs: false,
          clarification: "Which container?",
          answer: null,
          runtime_sources: [],
          doc_sources: [],
          execution: null,
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await sendChat({
      message: "It failed",
      conversationId: "conversation-1",
      sessionId: "session-1",
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      message: "It failed",
      conversation_id: "conversation-1",
      session_id: "session-1",
    });
  });

  it("turns backend detail responses into ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ detail: "Agent is disabled." }),
          {
            status: 409,
            headers: { "Content-Type": "application/json" },
          },
        ),
      ),
    );

    await expect(
      sendChat({ message: "hello" }),
    ).rejects.toEqual(
      expect.objectContaining<ApiError>({
        status: 409,
        detail: "Agent is disabled.",
      }),
    );
  });
});
