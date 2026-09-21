import { readdir, rm, stat } from "node:fs/promises";
const candidates = [
  new URL("../src/", import.meta.url),
  new URL("../vite.config.js", import.meta.url),
  new URL("../vite.config.js.map", import.meta.url),
  new URL("../tsconfig.tsbuildinfo", import.meta.url),
  new URL("../tsconfig.node.tsbuildinfo", import.meta.url),
];

async function exists(url) {
  try {
    await stat(url);
    return true;
  } catch {
    return false;
  }
}

async function cleanDirectory(url) {
  if (!(await exists(url))) {
    return;
  }

  for (const entry of await readdir(url, { withFileTypes: true })) {
    const child = new URL(`${entry.name}${entry.isDirectory() ? "/" : ""}`, url);
    if (entry.isDirectory()) {
      await cleanDirectory(child);
      continue;
    }

    if (
      entry.name.endsWith(".js") ||
      entry.name.endsWith(".js.map")
    ) {
      await rm(child, { force: true });
    }
  }
}

await cleanDirectory(candidates[0]);

for (const candidate of candidates.slice(1)) {
  if (await exists(candidate)) {
    await rm(candidate, { force: true });
  }
}

console.log("Removed stale TypeScript build artifacts.");
