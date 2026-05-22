/**
 * Phase 15D - frontend tests for the Topbar Safety Compact Pill.
 *
 * Pure helper tests cover the 7 visual states:
 *   - Loading
 *   - AI Paused (kill switch active)
 *   - AI Running + Sandbox ON + Briefing READY (info tone)
 *   - AI Running + Sandbox OFF + Briefing READY (success tone)
 *   - AI Running + Sandbox OFF + Briefing CRIT (danger tone)
 *   - Partial unavailability (kill-switch error → unavailable)
 *   - Full unavailability (all three errored)
 *
 * Topbar render tests confirm the helper's output reaches the DOM
 * via `topbar-safety-pill` testid and the `data-safety-tone` +
 * `data-safety-status` attributes.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import {
  __testing__,
  computeTopbarSafetySummary,
} from "@/utils/topbarSafetySummary";
import { Topbar } from "@/components/layout/Topbar";

// ---- api mock ----------------------------------------------------------

vi.mock("@/services/api", () => ({
  api: {
    getSaasRuntimeLiveGateKillSwitch: vi.fn(),
    getAiSandboxModeStatus: vi.fn(),
    getDirectorBriefingSidebarStatus: vi.fn(),
    getSaasCurrentOrganization: vi.fn().mockResolvedValue({
      organization: { id: 1, code: "nirogidhara", name: "Nirogidhara" },
      branch: null,
      userOrgRole: "owner",
      memberships: [],
      settings: [],
      featureFlags: [],
    }),
  },
}));

import { api } from "@/services/api";

// ---- fixtures ----------------------------------------------------------

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

const briefingReady = {
  status: "ready" as const,
  label: "Briefing ready",
  latestSnapshotId: 1,
  latestSnapshotAt: "2026-05-22T06:00:00Z",
  ageMinutes: 30,
  healthScore: 80,
  tier: "good",
  targetRoute: "/ceo-ai",
};

const briefingStale = {
  ...briefingReady,
  status: "stale" as const,
  label: "Briefing stale",
  ageMinutes: 60 * 48,
  healthScore: 60,
  tier: "fair",
};

const briefingCritical = {
  ...briefingReady,
  status: "critical" as const,
  label: "Briefing flags critical",
  healthScore: 15,
  tier: "critical",
};

// ---- Pure helper -------------------------------------------------------

describe("Phase 15D — computeTopbarSafetySummary", () => {
  it("returns Checking… while any fetch is still pending and no errors", () => {
    const res = computeTopbarSafetySummary({
      killSwitch: null,
      sandbox: null,
      briefing: null,
    });
    expect(res.label).toBe("Safety: Checking…");
    expect(res.tone).toBe("neutral");
    expect(res.dataStatus).toBe("loading");
  });

  it("flags AI Paused when kill switch is active (warning tone)", () => {
    const res = computeTopbarSafetySummary({
      killSwitch: killPaused,
      sandbox: sandboxOff,
      briefing: briefingStale,
    });
    expect(res.label).toBe(
      "Safety: AI Paused · Sandbox OFF · Briefing STALE",
    );
    expect(res.tone).toBe("warning");
    expect(res.dataStatus).toBe("ai_paused");
  });

  it("flags AI Running + Sandbox ON + Briefing READY (info tone)", () => {
    const res = computeTopbarSafetySummary({
      killSwitch: killRunning,
      sandbox: sandboxOn,
      briefing: briefingReady,
    });
    expect(res.label).toBe(
      "Safety: AI Running · Sandbox ON · Briefing READY",
    );
    expect(res.tone).toBe("info");
    expect(res.dataStatus).toBe("ai_running");
  });

  it("flags AI Running + Sandbox OFF + Briefing READY (success tone)", () => {
    const res = computeTopbarSafetySummary({
      killSwitch: killRunning,
      sandbox: sandboxOff,
      briefing: briefingReady,
    });
    expect(res.label).toBe(
      "Safety: AI Running · Sandbox OFF · Briefing READY",
    );
    expect(res.tone).toBe("success");
  });

  it("flags Briefing CRIT with danger tone even when AI is running and sandbox off", () => {
    const res = computeTopbarSafetySummary({
      killSwitch: killRunning,
      sandbox: sandboxOff,
      briefing: briefingCritical,
    });
    expect(res.label).toContain("Briefing CRIT");
    expect(res.tone).toBe("danger");
  });

  it("Briefing STALE escalates tone to warning when nothing higher fires", () => {
    const res = computeTopbarSafetySummary({
      killSwitch: killRunning,
      sandbox: sandboxOff,
      briefing: briefingStale,
    });
    expect(res.label).toContain("Briefing STALE");
    expect(res.tone).toBe("warning");
  });

  it("partial unavailability (sandbox errored) never asserts all-green", () => {
    const res = computeTopbarSafetySummary({
      killSwitch: killRunning,
      sandbox: null,
      sandboxError: true,
      briefing: briefingReady,
    });
    expect(res.label).toContain("Sandbox ?");
    expect(res.tone).toBe("warning");
  });

  it("kill-switch alone errored - posture neutral and unavailable", () => {
    const res = computeTopbarSafetySummary({
      killSwitch: null,
      killSwitchError: true,
      sandbox: sandboxOff,
      briefing: briefingReady,
    });
    expect(res.label).toContain("AI ?");
    expect(res.dataStatus).toBe("unavailable");
  });

  it("all three fetches errored renders 'State unavailable' (neutral tone)", () => {
    const res = computeTopbarSafetySummary({
      killSwitch: null,
      sandbox: null,
      briefing: null,
      killSwitchError: true,
      sandboxError: true,
      briefingError: true,
    });
    expect(res.label).toBe("Safety: State unavailable");
    expect(res.tone).toBe("neutral");
    expect(res.dataStatus).toBe("unavailable");
  });

  it("Briefing missing renders an em-dash without escalating tone", () => {
    const res = computeTopbarSafetySummary({
      killSwitch: killRunning,
      sandbox: sandboxOff,
      briefing: {
        ...briefingReady,
        status: "missing",
        latestSnapshotId: null,
        latestSnapshotAt: null,
      },
    });
    expect(res.label).toContain("Briefing —");
    // Missing briefing on a clean DB shouldn't escalate to warning
    // (it's the safe initial state) — success tone is appropriate.
    expect(res.tone).toBe("success");
  });

  it("__testing__.TONE_CLASS includes all five tones", () => {
    expect(__testing__.TONE_CLASS).toMatchObject({
      success: expect.any(String),
      info: expect.any(String),
      warning: expect.any(String),
      danger: expect.any(String),
      neutral: expect.any(String),
    });
  });
});

// ---- Topbar render -----------------------------------------------------

const renderTopbar = () =>
  render(
    <MemoryRouter>
      <Topbar onMenu={() => {}} />
    </MemoryRouter>,
  );

describe("Phase 15D — Topbar safety pill render", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders Checking… while any fetch is in flight", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockReturnValue(new Promise(() => {}));
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockReturnValue(new Promise(() => {}));
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockReturnValue(new Promise(() => {}));

    renderTopbar();

    const pill = await screen.findByTestId("topbar-safety-pill");
    expect(pill.getAttribute("data-safety-status")).toBe("loading");
    expect(pill.textContent || "").toContain("Checking");
  });

  it("renders 'AI Paused · Sandbox OFF · Briefing STALE' when kill switch is active", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(killPaused);
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOff);
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(briefingStale);

    renderTopbar();

    await waitFor(() =>
      expect(
        screen.getByTestId("topbar-safety-pill").getAttribute("data-safety-status"),
      ).toBe("ai_paused"),
    );
    const label = screen.getByTestId("topbar-safety-pill-label").textContent || "";
    expect(label).toContain("AI Paused");
    expect(label).toContain("Sandbox OFF");
    expect(label).toContain("Briefing STALE");
  });

  it("renders 'AI Running · Sandbox ON · Briefing READY' (info tone)", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(killRunning);
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOn);
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(briefingReady);

    renderTopbar();

    const pill = await screen.findByTestId("topbar-safety-pill");
    await waitFor(() =>
      expect(pill.getAttribute("data-safety-status")).toBe("ai_running"),
    );
    expect(pill.getAttribute("data-safety-tone")).toBe("info");
    const label = screen.getByTestId("topbar-safety-pill-label").textContent || "";
    expect(label).toContain("AI Running");
    expect(label).toContain("Sandbox ON");
    expect(label).toContain("Briefing READY");
  });

  it("renders 'State unavailable' when all three fetches fail", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockRejectedValue(new Error("HTTP 500"));
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockRejectedValue(new Error("HTTP 500"));
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockRejectedValue(new Error("HTTP 500"));

    renderTopbar();

    const pill = await screen.findByTestId("topbar-safety-pill");
    await waitFor(() =>
      expect(pill.getAttribute("data-safety-status")).toBe("unavailable"),
    );
    expect(screen.getByTestId("topbar-safety-pill-label").textContent).toBe(
      "Safety: State unavailable",
    );
  });

  it("never claims all-green when sandbox fetch errors mid-load", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(killRunning);
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockRejectedValue(new Error("HTTP 500"));
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(briefingReady);

    renderTopbar();

    const pill = await screen.findByTestId("topbar-safety-pill");
    await waitFor(() =>
      expect(
        (screen.getByTestId("topbar-safety-pill-label").textContent || ""),
      ).toContain("Sandbox ?"),
    );
    expect(pill.getAttribute("data-safety-tone")).toBe("warning");
  });

  it("preserves the existing Topbar AI Paused indicator alongside the pill", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(killPaused);
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOff);
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(briefingReady);

    renderTopbar();

    expect(
      await screen.findByTestId("topbar-kill-switch-paused"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("topbar-safety-pill")).toBeInTheDocument();
  });

  it("pill is read-only — no button/anchor and no click handler", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(killRunning);
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOff);
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(briefingReady);

    renderTopbar();

    const pill = await screen.findByTestId("topbar-safety-pill");
    expect(pill.tagName).toBe("SPAN");
    expect(pill.closest("a")).toBeNull();
    expect(pill.closest("button")).toBeNull();
    // No onclick attribute / no role="button".
    expect(pill.getAttribute("role")).toBe("status");
  });

  it("aria-label / title surface the long-form tooltip for screen readers", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(killPaused);
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOff);
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(briefingStale);

    renderTopbar();

    const pill = await screen.findByTestId("topbar-safety-pill");
    await waitFor(() =>
      expect(pill.getAttribute("data-safety-status")).toBe("ai_paused"),
    );
    const label = pill.getAttribute("aria-label") || "";
    expect(label).toContain("Kill Switch: Paused");
    expect(label).toContain("Sandbox: OFF");
    expect(label).toContain("Briefing: STALE");
    expect(label).toContain("Read-only");
    expect(pill.getAttribute("title")).toBe(label);
  });
});
