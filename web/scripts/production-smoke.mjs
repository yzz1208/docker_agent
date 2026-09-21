const appUrl = (
  process.env.APP_URL ?? "http://127.0.0.1:8080"
).replace(/\/$/, "");

async function fetchResponse(path) {
  const response = await fetch(`${appUrl}${path}`);
  const text = await response.text();
  return { response, text };
}

async function fetchText(path) {
  const result = await fetchResponse(path);
  if (!result.response.ok) {
    throw new Error(
      `GET ${path} failed with ${result.response.status}: ${result.text}`,
    );
  }
  return result;
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

console.log(`Production smoke testing ${appUrl}`);

for (const path of ["/", "/operations", "/settings"]) {
  const { response, text } = await fetchText(path);
  assert(
    response.headers.get("content-type")?.includes("text/html"),
    `${path} did not return HTML.`,
  );
  assert(
    text.includes('id="app"'),
    `${path} did not return the Vue application shell.`,
  );
  console.log(`✓ SPA route ${path}`);
}

const readiness = await fetchText("/health/ready");
const readinessPayload = JSON.parse(readiness.text);
assert(
  readinessPayload?.status === "ok" &&
    readinessPayload?.schema === "current",
  "Readiness endpoint is not healthy.",
);
console.log("✓ API readiness through Nginx");

const metrics = await fetchResponse("/metrics");
assert(
  metrics.response.status === 404,
  "Public Nginx must not expose /metrics.",
);
console.log("✓ Public metrics endpoint is closed");

console.log("Production smoke test passed.");
