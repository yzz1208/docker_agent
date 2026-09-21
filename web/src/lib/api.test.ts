import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  createAgentConfiguration,
  sendChat,
  updateAgentConfiguration,
} from "./api";

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

  it("serializes agent configuration create and update payloads", async () => {
    const responseBody = {
      agent_type: "docker_support",
      display_name: "Docker Expert",
      enabled: true,
      model_settings: { temperature: 0.3 },
      retrieval_settings: {},
      runtime_settings: {},
      created_at: "2026-09-21T03:00:00Z",
      updated_at: "2026-09-21T03:00:00Z",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify(responseBody), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await createAgentConfiguration({
      agent_type: "docker_support",
      display_name: "Docker Expert",
      enabled: true,
      model_settings: { temperature: 0.3 },
      retrieval_settings: {},
      runtime_settings: {},
    });
    await updateAgentConfiguration("docker_support", {
      enabled: false,
      runtime_settings: { max_steps: 6 },
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/agent-configurations",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          agent_type: "docker_support",
          display_name: "Docker Expert",
          enabled: true,
          model_settings: { temperature: 0.3 },
          retrieval_settings: {},
          runtime_settings: {},
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/agent-configurations/docker_support",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({
          enabled: false,
          runtime_settings: { max_steps: 6 },
        }),
      }),
    );
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
    ).rejects.toMatchObject({
      status: 409,
      detail: "Agent is disabled.",
    } satisfies Partial<ApiError>);
  });
});
