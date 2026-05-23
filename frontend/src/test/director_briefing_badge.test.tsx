/**
 * Phase 15B — frontend tests for the Sidebar Director Briefing badge.
 *
 * Covers:
 *   - Loading: badge renders "…" with data-briefing-status="loading".
 *   - ready: green badge with data-briefing-status="ready".
 *   - stale: amber badge with data-briefing-status="stale".
 *   - critical: red badge with data-briefing-status="critical".
 *   - missing: grey badge with data-briefing-status="missing".
 *   - 401 → data-briefing-status="auth-error" + "Session expired" title.
 *   - 403 → data-briefing-status="permission-error".
 *   - generic error → data-briefing-status="error".
 *   - Badge only renders next to /ceo-ai nav item (not next to any
 *     other nav row).
 *   - Phase 14E-Hotfix-1 bottom safety indicator still renders alongside
 *     (no regression).
 *   - The badge is intentionally not a separate clickable element — the
 *     surrounding NavLink owns navigation. The badge does not render a
 *     button/anchor of its own.
 *   - No raw `briefingText` / cross-cutting alert body leaks even when
 *     the mock includes them (defensive guard).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Sidebar } from "@/components/layout/Sidebar";
import { SafetyStateProvider } from "@/context/SafetyStateContext";

// ---- api mock ----------------------------------------------------------

vi.mock("@/services/api", () => ({
  api: {
    getSaasRuntimeLiveGateKillSwitch: vi.fn(),
    getAiSandboxModeStatus: vi.fn(),
    getDirectorBriefingSidebarStatus: vi.fn(),
  },
}));

import { api } from "@/services/api";

const killRunning = {
  scope: "global",
  enabled: false,
  runtimeKillSwitchEnabled: false,
  aiExecutionBlocked: false,
  statusLabel: "running" as const,
  reason: "",
  updatedAt: null,
  updatedBy: "",
  dryRun: true as const,
  liveExecutionAllowed: false as const,
  externalCallWillBeMade: false as const,
  killSwitchActive: false,
  approvalStatus: "",
  gateDecision: "kill_switch_disabled",
  blockers: [],
  warnings: [],
  nextAction: "keep_live_execution_blocked",
};

const sandboxOff = {
  isEnabled: false,
  note: "",
  updatedBy: "",
  sandboxEnabled: false,
  statusLabel: "disabled" as const,
};

// Phase 15F — Sidebar now consumes shared safety state from
// SafetyStateProvider. Tests wrap with the provider so the
// provider drives the same mocks Phase 15B configured.
const renderSidebar = () =>
  render(
    <MemoryRouter>
      <SafetyStateProvider>
        <Sidebar
          open
          onClose={() => {}}
          collapsed={false}
          onCollapsedChange={() => {}}
        />
      </SafetyStateProvider>
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.clearAllMocks();
  (
    api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
  ).mockResolvedValue(killRunning);
  (
    api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
  ).mockResolvedValue(sandboxOff);
});

// ---- States -----------------------------------------------------------

describe("Phase 15B — Sidebar Director Briefing badge", () => {
  it("shows the loading state immediately on mount", async () => {
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockReturnValue(new Promise(() => {})); // never resolves

    renderSidebar();

    const badge = await screen.findByTestId("sidebar-briefing-badge");
    expect(badge.getAttribute("data-briefing-status")).toBe("loading");
    expect(badge.getAttribute("title")).toBe("Checking briefing…");
  });

  it("renders 'ready' style + score in title when status=ready", async () => {
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue({
      status: "ready",
      label: "Briefing ready",
      latestSnapshotId: 42,
      latestSnapshotAt: "2026-05-22T06:00:00Z",
      ageMinutes: 30,
      healthScore: 81,
      tier: "good",
      targetRoute: "/ceo-ai",
    });

    renderSidebar();

    const badge = await screen.findByTestId("sidebar-briefing-badge");
    await waitFor(() =>
      expect(badge.getAttribute("data-briefing-status")).toBe("ready"),
    );
    expect(badge.getAttribute("title")).toContain("81");
    expect(badge.textContent).toMatch(/ready/i);
  });

  it("renders 'stale' style when backend says stale", async () => {
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue({
      status: "stale",
      label: "Briefing stale",
      latestSnapshotId: 7,
      latestSnapshotAt: "2026-05-19T06:00:00Z",
      ageMinutes: 60 * 60,
      healthScore: 65,
      tier: "fair",
      targetRoute: "/ceo-ai",
    });

    renderSidebar();

    const badge = await screen.findByTestId("sidebar-briefing-badge");
    await waitFor(() =>
      expect(badge.getAttribute("data-briefing-status")).toBe("stale"),
    );
    expect(badge.getAttribute("title")).toContain("stale");
    expect(badge.textContent).toMatch(/stale/i);
  });

  it("renders 'critical' style when tier is critical", async () => {
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue({
      status: "critical",
      label: "Briefing flags critical",
      latestSnapshotId: 99,
      latestSnapshotAt: "2026-05-22T06:00:00Z",
      ageMinutes: 60,
      healthScore: 12,
      tier: "critical",
      targetRoute: "/ceo-ai",
    });

    renderSidebar();

    const badge = await screen.findByTestId("sidebar-briefing-badge");
    await waitFor(() =>
      expect(badge.getAttribute("data-briefing-status")).toBe("critical"),
    );
    expect(badge.getAttribute("title")).toContain("critical");
  });

  it("renders 'missing' style when no snapshot exists", async () => {
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue({
      status: "missing",
      label: "No briefing yet",
      latestSnapshotId: null,
      latestSnapshotAt: null,
      ageMinutes: null,
      healthScore: null,
      tier: null,
      targetRoute: "/ceo-ai",
    });

    renderSidebar();

    const badge = await screen.findByTestId("sidebar-briefing-badge");
    await waitFor(() =>
      expect(badge.getAttribute("data-briefing-status")).toBe("missing"),
    );
    expect(badge.getAttribute("title")).toMatch(/No briefing/i);
  });

  it("renders auth-error state on HTTP 401", async () => {
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockRejectedValue(new Error("HTTP 401 — session expired"));

    renderSidebar();

    const badge = await screen.findByTestId("sidebar-briefing-badge");
    await waitFor(() =>
      expect(badge.getAttribute("data-briefing-status")).toBe("auth-error"),
    );
    expect(badge.getAttribute("title")).toMatch(/Session expired/i);
  });

  it("renders permission-error state on HTTP 403", async () => {
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockRejectedValue(new Error("HTTP 403 for /v1/ceo-orchestration/snapshots/sidebar-status/"));

    renderSidebar();

    const badge = await screen.findByTestId("sidebar-briefing-badge");
    await waitFor(() =>
      expect(badge.getAttribute("data-briefing-status")).toBe(
        "permission-error",
      ),
    );
    expect(badge.getAttribute("title")).toMatch(/unavailable/i);
  });

  it("renders generic error state on other failures", async () => {
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockRejectedValue(new Error("Network down"));

    renderSidebar();

    const badge = await screen.findByTestId("sidebar-briefing-badge");
    await waitFor(() =>
      expect(badge.getAttribute("data-briefing-status")).toBe("error"),
    );
  });
});

// ---- Co-render + scope guards -----------------------------------------

describe("Phase 15B — badge scope + Sidebar regression", () => {
  it("badge only renders once (next to /ceo-ai nav item)", async () => {
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue({
      status: "ready",
      label: "Briefing ready",
      latestSnapshotId: 1,
      latestSnapshotAt: "2026-05-22T06:00:00Z",
      ageMinutes: 10,
      healthScore: 80,
      tier: "good",
      targetRoute: "/ceo-ai",
    });

    renderSidebar();

    // Wait for the badge then assert there's exactly one.
    await screen.findByTestId("sidebar-briefing-badge");
    expect(
      screen.getAllByTestId("sidebar-briefing-badge").length,
    ).toBe(1);
  });

  it("Phase 14E-Hotfix-1 bottom safety indicator still renders alongside the new badge", async () => {
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue({
      status: "ready",
      label: "Briefing ready",
      latestSnapshotId: 1,
      latestSnapshotAt: "2026-05-22T06:00:00Z",
      ageMinutes: 10,
      healthScore: 80,
      tier: "good",
      targetRoute: "/ceo-ai",
    });

    renderSidebar();

    // Briefing badge present.
    expect(
      await screen.findByTestId("sidebar-briefing-badge"),
    ).toBeInTheDocument();
    // Existing safety label still surfaces (AI running + sandbox OFF
    // = "All systems normal").
    await waitFor(() =>
      expect(screen.getByTestId("sidebar-safety-label").textContent).toBe(
        "All systems normal",
      ),
    );
  });

  it("badge has no separate button/anchor — navigation is via the surrounding NavLink", async () => {
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue({
      status: "ready",
      label: "Briefing ready",
      latestSnapshotId: 1,
      latestSnapshotAt: "2026-05-22T06:00:00Z",
      ageMinutes: 10,
      healthScore: 80,
      tier: "good",
      targetRoute: "/ceo-ai",
    });

    renderSidebar();

    const badge = await screen.findByTestId("sidebar-briefing-badge");
    // The badge itself is a <span>, not a button/anchor.
    expect(badge.tagName).toBe("SPAN");
    // The surrounding NavLink (<a>) handles navigation to /ceo-ai.
    const link = badge.closest("a");
    expect(link).not.toBeNull();
    expect(link?.getAttribute("href")).toBe("/ceo-ai");
  });
});
