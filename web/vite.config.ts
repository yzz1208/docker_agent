import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";

const backendTarget =
  process.env.VITE_BACKEND_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [vue()],
  test: {
    include: ["src/**/*.test.ts"],
  },
  server: {
    port: 5173,
    proxy: {
      "/chat": backendTarget,
      "/conversations": backendTarget,
      "/agent-configurations": backendTarget,
      "^/operations/(runs|summary|evaluations)": backendTarget,
      "/health": backendTarget,
    },
  },
});
