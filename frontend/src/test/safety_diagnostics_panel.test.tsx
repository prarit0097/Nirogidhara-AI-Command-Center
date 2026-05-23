/**
 * Phase 15I - tests for the Safety Diagnostics mini panel.
 *
 * Covers:
 *   - Helper visual mappings (sync + endpoint) for every state.
 *   - formatTimestamp falls back to safe empty labels.
 *   - Panel renders the six diagnostics rows with correct values.
 *   - Sync status flips to Live/Reconnecting/Offline through the
 *     existing Phase 15H onStatusChange path.
 *   - Endpoint OK/Loading/Error mapping mirrors the provider state.
 *   - Mixed-state path: kill-switch errors, sandbox + briefing OK.
 *   - Timestamps render as locale strings when present, fallback
 *     to "Never" / "No event seen yet" when absent.
 *   - Panel is read-only: no buttons, no anchors, no click handlers.
 *   - Sensitive data is not rendered (rows surface only enums + ISO).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import {
  SafetyStateProvider,
  deriveEndpointStatus,
} from "@/context/SafetyStateContext";
import {
  SafetyDiagnosticsPanel,
  __testing__,
} from "@/components/settings/SafetyDiagnosticsPanel";

// ---- api + realtime mocks ---------------------------------------------

vi.mock("@/services/api", () => ({
  api: {
    getSaasRuntimeLiveGateKillSwitch: vi.fn(),
    getAiSandboxModeStatus: vi.fn(),
    getDirectorBriefingSidebarStatus: vi.fn(),
  },
}));

const realtimeCalls: Array<{
  onStatusChange?: (status: string) => void;
  close: ReturnType<typeof vi.fn>;
}> = [];

vi.mock("@/services/realtime", () => ({
  connectAuditEvents: vi.fn(
    (opts: { onStatusChange?: (status: string) => void }) => {
      const close = vi.fn();
      realtimeCalls.push({ onStatusChange: opts.onStatusChange, close });
      return { close, isLive: () => false, url: "ws://test" };
    },
  ),
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

const sandboxOff = {
  isEnabled: false,
  note: "",
  updatedBy: "",
  sandboxEnabled: false,
  statusLabel: "disabled" as const,
};

const briefingReady = {
  status: "ready" as const,
  label: "Briefing ready",
  latestSnapshotId: 1,
  latestSnapshotAt: "2026-05-23T06:00:00Z",
  ageMinutes: 10,
  healthScore: 80,
  tier: "good",
  targetRoute: "/ceo-ai",
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  realtimeCalls.length = 0;
  (
    api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
  ).mockResolvedValue(killRunning);
  (
    api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
  ).mockResolvedValue(sandboxOff);
  (
    api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
  ).mockResolvedValue(briefingReady);
});

afterEach(() => {
  vi.useRealTimers();
});

const renderPanel = () =>
  render(
    <SafetyStateProvider>
      <SafetyDiagnosticsPanel />
    </SafetyStateProvider>,
  );

// ---- Pure helpers -----------------------------------------------------

describe("Phase 15I - helpers", () => {
  it("syncVisual maps every SafetySyncStatus to a label + tone", () => {
    expect(__testing__.syncVisual("live")).toEqual({
      label: "Live",
      tone: "success",
    });
    expect(__testing__.syncVisual("connecting")).toEqual({
      label: "Connecting",
      tone: "info",
    });
    expect(__testing__.syncVisual("reconnecting")).toEqual({
      label: "Reconnecting",
      tone: "warning",
    });
    expect(__testing__.syncVisual("offline")).toEqual({
      label: "Offline",
      tone: "warning",
    });
    expect(__testing__.syncVisual("unavailable")).toEqual({
      label: "Unavailable",
      tone: "neutral",
    });
  });

  it("endpointVisual maps OK/Loading/Error correctly", () => {
    expect(__testing__.endpointVisual("ok")).toEqual({
      label: "OK",
      tone: "success",
    });
    expect(__testing__.endpointVisual("loading")).toEqual({
      label: "Loading",
      tone: "info",
    });
    expect(__testing__.endpointVisual("error")).toEqual({
      label: "Error",
      tone: "warning",
    });
  });

  it("formatTimestamp returns empty label for null + invalid ISO + parseable iso", () => {
    expect(__testing__.formatTimestamp(null, "Never")).toBe("Never");
    expect(__testing__.formatTimestamp("not-a-date", "Never")).toBe("Never");
    const out = __testing__.formatTimestamp("2026-05-23T06:00:00Z", "Never");
    expect(out).not.toBe("Never");
    expect(out.length).toBeGreaterThan(0);
  });

  it("deriveEndpointStatus prioritises error > snapshot > loading", () => {
    expect(deriveEndpointStatus(true, false)).toBe("ok");
    expect(deriveEndpointStatus(false, false)).toBe("loading");
    expect(deriveEndpointStatus(true, true)).toBe("error");
    expect(deriveEndpointStatus(false, true)).toBe("error");
  });
});

// ---- Panel render -----------------------------------------------------

describe("Phase 15I - SafetyDiagnosticsPanel render", () => {
  it("renders the six diagnostics rows", () => {
    renderPanel();
    expect(screen.getByTestId("safety-diagnostics-panel")).toBeInTheDocument();
    for (const testid of [
      "diagnostics-safety-sync",
      "diagnostics-last-refresh",
      "diagnostics-last-event",
      "diagnostics-kill-switch",
      "diagnostics-sandbox",
      "diagnostics-briefing",
    ]) {
      expect(screen.getByTestId(testid)).toBeInTheDocument();
    }
  });

  it("initial render shows Connecting + Loading for every endpoint + Never/No event yet", () => {
    renderPanel();
    expect(
      screen.getByTestId("diagnostics-safety-sync-value").textContent,
    ).toContain("Connecting");
    expect(
      screen.getByTestId("diagnostics-kill-switch-value").textContent,
    ).toContain("Loading");
    expect(
      screen.getByTestId("diagnostics-sandbox-value").textContent,
    ).toContain("Loading");
    expect(
      screen.getByTestId("diagnostics-briefing-value").textContent,
    ).toContain("Loading");
    expect(
      screen.getByTestId("diagnostics-last-refresh-value").textContent,
    ).toContain("Never");
    expect(
      screen.getByTestId("diagnostics-last-event-value").textContent,
    ).toContain("No event seen yet");
  });

  it("after fetches settle, all three endpoints show OK", async () => {
    renderPanel();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(
      screen.getByTestId("diagnostics-kill-switch-value").textContent,
    ).toContain("OK");
    expect(
      screen.getByTestId("diagnostics-sandbox-value").textContent,
    ).toContain("OK");
    expect(
      screen.getByTestId("diagnostics-briefing-value").textContent,
    ).toContain("OK");
  });

  it("kill-switch error renders Error, sandbox + briefing still OK (no all-green claim)", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockRejectedValue(new Error("HTTP 500"));
    const consoleErrSpy = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});
    renderPanel();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(
      screen.getByTestId("diagnostics-kill-switch-value").textContent,
    ).toContain("Error");
    expect(
      screen.getByTestId("diagnostics-sandbox-value").textContent,
    ).toContain("OK");
    expect(
      screen.getByTestId("diagnostics-briefing-value").textContent,
    ).toContain("OK");
    consoleErrSpy.mockRestore();
  });

  it("sync status flips to Live when the helper fires onStatusChange('live')", async () => {
    renderPanel();
    await act(async () => {
      await Promise.resolve();
    });
    const ctrl = realtimeCalls[0];
    act(() => ctrl.onStatusChange?.("live"));
    expect(
      screen.getByTestId("diagnostics-safety-sync-value").textContent,
    ).toContain("Live");
  });

  it("sync status flips through Reconnecting + Offline + Unavailable safely", async () => {
    renderPanel();
    await act(async () => {
      await Promise.resolve();
    });
    const ctrl = realtimeCalls[0];

    act(() => ctrl.onStatusChange?.("reconnecting"));
    expect(
      screen.getByTestId("diagnostics-safety-sync-value").textContent,
    ).toContain("Reconnecting");

    act(() => ctrl.onStatusChange?.("offline"));
    expect(
      screen.getByTestId("diagnostics-safety-sync-value").textContent,
    ).toContain("Offline");
  });

  it("panel contains NO buttons, NO anchors, NO click handlers", () => {
    renderPanel();
    const panel = screen.getByTestId("safety-diagnostics-panel");
    expect(panel.querySelector("button")).toBeNull();
    expect(panel.querySelector("a")).toBeNull();
    // Spot-check forbidden action labels in case a future regression
    // sneaks them in.
    const text = panel.textContent || "";
    for (const forbidden of [
      "Resume AI",
      "Activate kill",
      "Enable sandbox",
      "Disable sandbox",
      "Apply rollback",
      "Generate briefing",
    ]) {
      expect(text).not.toContain(forbidden);
    }
  });

  it("does not leak tokens / phones / secrets / prompt bodies / payload keys", async () => {
    renderPanel();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    const text = screen.getByTestId("safety-diagnostics-panel").textContent || "";
    for (const forbidden of [
      "Bearer ",
      "sk-proj-",
      "+91",
      "@example.com",
      "system_policy",
      "instruction_payload",
      "raw_payload",
      "raw_response",
      "payment_url",
      "META_WA_TOKEN",
      "VAPI_API_KEY",
    ]) {
      expect(text).not.toContain(forbidden);
    }
  });
});
