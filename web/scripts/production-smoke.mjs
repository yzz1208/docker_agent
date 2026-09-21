const appUrl = (
  process.env.APP_URL ?? "http://127.0.0.1:8080"
).replace(/\/$/, "");

async function fetchText(path) {
  const response = await fetch(`${appUrl}${path}`);
  const text = await response.text();
  if (!response.ok) {
    throw new Error(
      `GET ${path} failed with ${response.status}: ${text}`,
    );
  }
  return { response, text };
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

const metrics = await fetchText("/metrics");
assert(
  metrics.text.includes("docker_agent_http_requests_total") &&
    metrics.text.includes("docker_agent_run_duration_seconds"),
  "Prometheus metrics are missing expected Agent metrics.",
);
console.log("✓ Prometheus metrics through Nginx");

console.log("Production smoke test passed.");
