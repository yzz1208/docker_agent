const backendUrl = (
  process.env.BACKEND_URL ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");

async function request(path, init = {}) {
  const response = await fetch(`${backendUrl}${path}`, init);
  let payload = null;

  if (response.status !== 204) {
    const text = await response.text();
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = text;
      }
    }
  }

  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? payload.detail
        : payload;
    throw new Error(
      `${init.method ?? "GET"} ${path} failed with ${response.status}: ${String(
        detail ?? response.statusText,
      )}`,
    );
  }

  return payload;
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

console.log(`Smoke testing ${backendUrl}`);

const health = await request("/health");
assert(health?.status === "ok", "System health did not return status=ok.");
console.log("✓ API health");

const database = await request("/health/db");
assert(
  database?.database === "reachable",
  "Database health did not report reachable.",
);
console.log("✓ Database health");

const effective = await request(
  "/agent-configurations/docker_support/effective",
);
assert(
  effective?.agent_type === "docker_support",
  "Effective configuration did not resolve docker_support.",
);
assert(
  !JSON.stringify(effective).includes("model_api_key\":\""),
  "Effective configuration appears to expose an API key value.",
);
console.log("✓ Effective configuration");

const conversations = await request(
  "/conversations?limit=1&offset=0",
);
assert(
  Array.isArray(conversations),
  "Conversation listing did not return an array.",
);
console.log("✓ Conversation listing");

const smokeMessage = process.env.SMOKE_CHAT_MESSAGE?.trim();
if (smokeMessage) {
  console.log(
    "Running optional chat smoke. This invokes the agent and may use model/tool resources.",
  );

  let createdConversationId = null;
  try {
    const turn = await request("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: smokeMessage,
        conversation_id: null,
        session_id: null,
      }),
    });

    createdConversationId = turn?.conversation_id ?? null;
    assert(
      typeof turn?.route === "string",
      "Chat smoke did not return a route.",
    );
    assert(
      typeof turn?.session_id === "string",
      "Chat smoke did not return a session id.",
    );
    console.log("✓ Optional chat turn");
  } finally {
    if (createdConversationId) {
      await request(
        `/conversations/${encodeURIComponent(createdConversationId)}`,
        { method: "DELETE" },
      );
      console.log("✓ Optional chat cleanup");
    }
  }
}

console.log("Smoke test passed.");
