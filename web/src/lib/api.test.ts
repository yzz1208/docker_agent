import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  compareEvaluationRuns,
  createAgentConfiguration,
  getAgentDescriptor,
  getOperationsSummary,
  listAgentRuns,
  listAgents,
  listEvaluationRuns,
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
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify(responseBody), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
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

  it("loads registered Agent descriptors", async () => {
    const descriptor = {
      agent_type: "docker_support",
      display_name: "Docker Support",
      description: "Docker support",
      capabilities: ["chat"],
      knowledge_sources: ["docker_docs"],
      toolsets: ["docker_read_only"],
      worker_roles: ["knowledge"],
      configuration_groups: ["model_settings"],
      default_enabled: true,
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify([descriptor]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(descriptor), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(listAgents()).resolves.toEqual([descriptor]);
    await expect(
      getAgentDescriptor("Docker Support"),
    ).resolves.toEqual(descriptor);

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/agents");
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      "/agents/Docker%20Support",
    );
  });

  it("serializes operations filters and comparison queries", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await listAgentRuns({
      conversationId: "conversation 1",
      agentType: "docker_support",
      status: "failed",
      limit: 25,
      offset: 5,
    });
    await getOperationsSummary(168);
    await listEvaluationRuns({
      suite: "agent_router",
      limit: 10,
      offset: 2,
    });
    await compareEvaluationRuns({
      baselineId: "baseline-1",
      candidateId: "candidate-2",
      maxRegression: 0.01,
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/operations/runs?conversation_id=conversation+1" +
        "&agent_type=docker_support&status=failed&limit=25&offset=5",
    );
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      "/operations/summary?hours=168",
    );
    expect(fetchMock.mock.calls[2]?.[0]).toBe(
      "/operations/evaluations?limit=10&offset=2&suite=agent_router",
    );
    expect(fetchMock.mock.calls[3]?.[0]).toBe(
      "/operations/evaluations/compare?baseline_id=baseline-1" +
        "&candidate_id=candidate-2&max_regression=0.01",
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
