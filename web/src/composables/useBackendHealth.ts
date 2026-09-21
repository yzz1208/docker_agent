import { computed, ref } from "vue";

import { ApiError, getDatabaseHealth, getSystemHealth } from "../lib/api";

export type BackendHealthState =
  | "checking"
  | "healthy"
  | "degraded"
  | "offline";

export function useBackendHealth() {
  const state = ref<BackendHealthState>("checking");
  const apiReachable = ref(false);
  const databaseReachable = ref(false);
  const detail = ref("Checking backend…");
  const lastCheckedAt = ref<Date | null>(null);

  let requestVersion = 0;
  let timer: ReturnType<typeof setInterval> | null = null;

  const label = computed(() => {
    switch (state.value) {
      case "healthy":
        return "Backend healthy";
      case "degraded":
        return "Backend degraded";
      case "offline":
        return "Backend offline";
      default:
        return "Checking backend";
    }
  });

  async function check(): Promise<void> {
    const version = ++requestVersion;
    state.value = "checking";

    try {
      await getSystemHealth();
      if (version !== requestVersion) {
        return;
      }
      apiReachable.value = true;
    } catch (error) {
      if (version !== requestVersion) {
        return;
      }
      apiReachable.value = false;
      databaseReachable.value = false;
      state.value = "offline";
      detail.value =
        error instanceof Error ? error.message : "Backend is unreachable.";
      lastCheckedAt.value = new Date();
      return;
    }

    try {
      await getDatabaseHealth();
      if (version !== requestVersion) {
        return;
      }
      databaseReachable.value = true;
      state.value = "healthy";
      detail.value = "API and PostgreSQL are reachable.";
    } catch (error) {
      if (version !== requestVersion) {
        return;
      }
      databaseReachable.value = false;
      state.value = "degraded";
      detail.value =
        error instanceof ApiError
          ? error.detail
          : error instanceof Error
            ? error.message
            : "Database health check failed.";
    } finally {
      if (version === requestVersion) {
        lastCheckedAt.value = new Date();
      }
    }
  }

  function start(intervalMs = 30_000): void {
    void check();
    if (timer !== null) {
      clearInterval(timer);
    }
    timer = setInterval(() => {
      void check();
    }, intervalMs);
  }

  function stop(): void {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
    requestVersion += 1;
  }


  return {
    state,
    apiReachable,
    databaseReachable,
    detail,
    lastCheckedAt,
    label,
    check,
    start,
    stop,
  };
}
