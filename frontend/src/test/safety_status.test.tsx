/**
 * Phase 14E-Hotfix-1 — tests for the safety status helper + the
 * Sidebar bottom indicator wiring.
 *
 * Pure helper tests (computeSafetyStatus) cover the 5 priority cases:
 *   - loading
 *   - error (either backend fetch failed)
 *   - kill switch paused
 *   - sandbox ON
 *   - both green
 *
 * Sidebar render tests confirm the helper's output reaches the DOM
 * with the right label + tone.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { computeSafetyStatus } from "@/utils/safetyStatus";
import { Sidebar } from "@/components/layout/Sidebar";

// ---- api mock ----------------------------------------------------------

vi.mock("@/services/api", () => ({
  api: {
    getSaasRuntimeLiveGateKillSwitch: vi.fn(),
    getAiSandboxModeStatus: vi.fn(),
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

const killPaused = {
  ...killRunning,
  enabled: true,
  runtimeKillSwitchEnabled: true,
  aiExecutionBlocked: true,
  statusLabel: "paused" as const,
  killSwitchActive: true,
  gateDecision: "blocked_by_kill_switch",
};

const sandboxOff = {
  isEnabled: false,
  note: "",
  updatedBy: "",
  sandboxEnabled: false,
  statusLabel: "disabled" as const,
};

const sandboxOn = {
  isEnabled: true,
  note: "",
  updatedBy: "",
  sandboxEnabled: true,
  statusLabel: "enabled" as const,
};

// ---- Pure helper -------------------------------------------------------

describe("Phase 14E-Hotfix-1 — computeSafetyStatus priority", () => {
  it("returns Loading when either fetch is still pending (both null, no errors)", () => {
    const res = computeSafetyStatus({
      killSwitch: null,
      sandbox: null,
    });
    expect(res.label).toBe("Checking safety state…");
    expect(res.tone).toBe("neutral");
  });

  it("returns Unavailable when either fetch errored", () => {
    const res = computeSafetyStatus({
      killSwitch: null,
      sandbox: sandboxOff,
      killSwitchError: true,
    });
    expect(res.label).toBe("Safety state unavailable");
    expect(res.tone).toBe("neutral");
  });

  it("returns 'AI paused by kill switch' when kill switch is active (overrides sandbox)", () => {
    const res = computeSafetyStatus({
      killSwitch: killPaused,
      // Even if sandbox is also ON, kill-switch paused wins.
      sandbox: sandboxOn,
    });
    expect(res.label).toBe("AI paused by kill switch");
    expect(res.tone).toBe("warning");
  });

  it("returns 'Sandbox mode active' when AI running and sandbox ON", () => {
    const res = computeSafetyStatus({
      killSwitch: killRunning,
      sandbox: sandboxOn,
    });
    expect(res.label).toBe("Sandbox mode active");
    expect(res.tone).toBe("info");
  });

  it("returns 'All systems normal' when AI running and sandbox OFF", () => {
    const res = computeSafetyStatus({
      killSwitch: killRunning,
      sandbox: sandboxOff,
    });
    expect(res.label).toBe("All systems normal");
    expect(res.tone).toBe("success");
  });

  it("never asserts normal when sandbox fetch errors mid-load", () => {
    const res = computeSafetyStatus({
      killSwitch: killRunning,
      sandbox: null,
      sandboxError: true,
    });
    expect(res.label).toBe("Safety state unavailable");
  });
});

// ---- Sidebar render ----------------------------------------------------

const renderSidebar = () =>
  render(
    <MemoryRouter>
      <Sidebar
        open
        onClose={() => {}}
        collapsed={false}
        onCollapsedChange={() => {}}
      />
    </MemoryRouter>,
  );

describe("Phase 14E-Hotfix-1 — Sidebar safety indicator", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows 'AI paused by kill switch' when kill switch is active (sandbox OFF)", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(killPaused);
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOff);

    renderSidebar();

    await waitFor(() =>
      expect(screen.getByTestId("sidebar-safety-label").textContent).toBe(
        "AI paused by kill switch",
      ),
    );
    // The legacy "All systems normal" copy must NOT be visible while
    // kill switch is active.
    expect(
      screen.queryByText(/All systems normal/i),
    ).toBeNull();
  });

  it("shows 'Sandbox mode active' when AI running but sandbox is ON", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(killRunning);
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOn);

    renderSidebar();

    await waitFor(() =>
      expect(screen.getByTestId("sidebar-safety-label").textContent).toBe(
        "Sandbox mode active",
      ),
    );
  });

  it("shows 'All systems normal' when AI running and sandbox OFF", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(killRunning);
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOff);

    renderSidebar();

    await waitFor(() =>
      expect(screen.getByTestId("sidebar-safety-label").textContent).toBe(
        "All systems normal",
      ),
    );
  });

  it("shows 'Safety state unavailable' when either backend fetch errors", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockRejectedValue(new Error("HTTP 500"));
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOff);

    renderSidebar();

    await waitFor(() =>
      expect(screen.getByTestId("sidebar-safety-label").textContent).toBe(
        "Safety state unavailable",
      ),
    );
    // Critically: do NOT show "All systems normal" while a fetch
    // errored — operators must not be told everything is fine when
    // the safety surface itself is degraded.
    expect(
      screen.queryByText(/All systems normal/i),
    ).toBeNull();
  });
});
