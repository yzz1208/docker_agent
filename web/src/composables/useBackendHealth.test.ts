import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    detail: string;

    constructor(status: number, detail: string) {
      super(detail);
      this.status = status;
      this.detail = detail;
    }
  },
  getDatabaseHealth: vi.fn(),
  getSystemHealth: vi.fn(),
}));

import {
  ApiError,
  getDatabaseHealth,
  getSystemHealth,
} from "../lib/api";
import { useBackendHealth } from "./useBackendHealth";

beforeEach(() => {
  vi.resetAllMocks();
});

describe("backend health", () => {
  it("reports healthy when API and database are reachable", async () => {
    vi.mocked(getSystemHealth).mockResolvedValue({
      status: "ok",
      app: "docker-agent",
      env: "test",
    });
    vi.mocked(getDatabaseHealth).mockResolvedValue({
      status: "ok",
      database: "reachable",
    });

    const health = useBackendHealth();
    await health.check();

    expect(health.state.value).toBe("healthy");
    expect(health.apiReachable.value).toBe(true);
    expect(health.databaseReachable.value).toBe(true);
    expect(health.label.value).toBe("后端正常");
  });

  it("reports degraded when the API is reachable but database is not", async () => {
    vi.mocked(getSystemHealth).mockResolvedValue({
      status: "ok",
      app: "docker-agent",
      env: "test",
    });
    vi.mocked(getDatabaseHealth).mockRejectedValue(
      new ApiError(503, "PostgreSQL is unavailable."),
    );

    const health = useBackendHealth();
    await health.check();

    expect(health.state.value).toBe("degraded");
    expect(health.apiReachable.value).toBe(true);
    expect(health.databaseReachable.value).toBe(false);
    expect(health.detail.value).toBe("PostgreSQL is unavailable.");
  });

  it("reports offline when the API health endpoint is unreachable", async () => {
    vi.mocked(getSystemHealth).mockRejectedValue(
      new TypeError("Failed to fetch"),
    );

    const health = useBackendHealth();
    await health.check();

    expect(health.state.value).toBe("offline");
    expect(health.apiReachable.value).toBe(false);
    expect(health.databaseReachable.value).toBe(false);
    expect(getDatabaseHealth).not.toHaveBeenCalled();
  });
});
