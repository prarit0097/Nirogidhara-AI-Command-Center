import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/services/api";

const originalFetch = global.fetch;

describe("api service — mock fallback", () => {
  beforeEach(() => {
    // Force every fetch to fail so the fallback path runs.
    global.fetch = vi.fn().mockRejectedValue(new Error("network down")) as typeof fetch;
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("falls back to mock leads when the backend is unreachable", async () => {
    const leads = await api.getLeads();
    expect(Array.isArray(leads)).toBe(true);
    expect(leads.length).toBeGreaterThan(0);
    expect(leads[0]).toHaveProperty("id");
    expect(leads[0]).toHaveProperty("qualityScore");
  });

  it("falls back to mock dashboard metrics when the backend is unreachable", async () => {
    const metrics = await api.getDashboardMetrics();
    expect(metrics.leadsToday.value).toBeGreaterThan(0);
    expect(metrics.netProfit.value).toBeGreaterThan(0);
  });

  it("falls back to mock CEO briefing when the backend is unreachable", async () => {
    const briefing = await api.getCeoBriefing();
    expect(briefing.recommendations.length).toBeGreaterThan(0);
    expect(briefing.headline).toBeTruthy();
  });
});
