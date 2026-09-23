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
  const detail = ref("正在检查后端状态…");
  const lastCheckedAt = ref<Date | null>(null);

  let requestVersion = 0;
  let timer: ReturnType<typeof setInterval> | null = null;

  const label = computed(() => {
    switch (state.value) {
      case "healthy":
        return "后端正常";
      case "degraded":
        return "后端降级";
      case "offline":
        return "后端离线";
      default:
        return "检查中";
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
        error instanceof Error ? error.message : "无法连接后端。";
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
      detail.value = "API 与 PostgreSQL 连接正常。";
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
            : "数据库健康检查失败。";
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
