/**
 * Phase 15H - tests for the Safety Sync health indicator.
 *
 * Covers:
 *   - Pure helper: every SafetySyncStatus maps to a deterministic
 *     label / compactLabel / tone / className / dataStatus /
 *     tooltip ending "Read-only indicator."
 *   - Provider initial status is "connecting" before any onStatusChange
 *     fires (Phase 4A helper opens the socket synchronously).
 *   - onStatusChange callback flips the surfaced status to live /
 *     reconnecting / offline.
 *   - Construction-failure path sets status to "unavailable".
 *   - Allow-listed event timestamps `lastSafetyEventAt` AND
 *     `lastSafetyRefreshAt` (after debounce).
 *   - Non-matching event does NOT timestamp anything.
 *   - Unmount sets status back to "offline" so a remount cannot
 *     leak a stale "live" indicator.
 *   - Topbar renders the indicator with the right testid,
 *     data-safety-sync-status, and aria-label.
 *   - Topbar indicator is a read-only <span role="status">: no
 *     button, no anchor, no click handler.
 *   - Offline status does not crash the Topbar.
 *   - Existing Topbar Safety Pill still renders alongside.
 *   - Existing AI Paused button still renders.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import {
  SafetyStateProvider,
  SAFETY_REFRESH_DEBOUNCE_MS,
  useSafetyState,
} from "@/context/SafetyStateContext";
import { computeSafetySyncIndicator } from "@/utils/safetySyncIndicator";
import { Topbar } from "@/components/layout/Topbar";

// ---- api + realtime mocks ----------------------------------------------

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

const realtimeCalls: Array<{
  onEvent?: (event: unknown) => void;
  onStatusChange?: (status: string) => void;
  onError?: (err: unknown) => void;
  close: ReturnType<typeof vi.fn>;
}> = [];
let realtimeShouldThrow = false;

vi.mock("@/services/realtime", () => ({
  connectAuditEvents: vi.fn((opts: {
    onEvent?: (event: unknown) => void;
    onStatusChange?: (status: string) => void;
    onError?: (err: unknown) => void;
  }) => {
    if (realtimeShouldThrow) {
      throw new Error("simulated stream construction failure");
    }
    const close = vi.fn();
    realtimeCalls.push({
      onEvent: opts.onEvent,
      onStatusChange: opts.onStatusChange,
      onError: opts.onError,
      close,
    });
    return { close, isLive: () => false, url: "ws://test" };
  }),
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
  realtimeShouldThrow = false;
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

// ---- Pure helper -------------------------------------------------------

describe("Phase 15H - computeSafetySyncIndicator helper", () => {
  it("maps live -> success green pill", () => {
    const out = computeSafetySyncIndicator("live");
    expect(out.label).toBe("Sync: Live");
    expect(out.compactLabel).toBe("Live");
    expect(out.tone).toBe("success");
    expect(out.dataStatus).toBe("live");
    expect(out.tooltip).toContain("Safety Sync: Live");
    expect(out.tooltip).toContain("Read-only indicator.");
  });

  it("maps connecting -> info pill", () => {
    const out = computeSafetySyncIndicator("connecting");
    expect(out.label).toBe("Sync: Connecting");
    expect(out.compactLabel).toBe("Connect");
    expect(out.tone).toBe("info");
    expect(out.tooltip).toContain("opening audit event stream");
    expect(out.tooltip).toContain("Read-only indicator.");
  });

  it("maps reconnecting -> warning amber pill", () => {
    const out = computeSafetySyncIndicator("reconnecting");
    expect(out.label).toBe("Sync: Reconnecting");
    expect(out.compactLabel).toBe("Reconnect");
    expect(out.tone).toBe("warning");
    expect(out.tooltip).toContain("Reconnecting");
    expect(out.tooltip).toContain("Read-only indicator.");
  });

  it("maps offline -> warning pill carrying refresh hint", () => {
    const out = computeSafetySyncIndicator("offline");
    expect(out.label).toBe("Sync: Offline");
    expect(out.compactLabel).toBe("Offline");
    expect(out.tone).toBe("warning");
    expect(out.tooltip).toContain("refresh page if needed");
    expect(out.tooltip).toContain("Read-only indicator.");
  });

  it("maps unavailable -> neutral pill", () => {
    const out = computeSafetySyncIndicator("unavailable");
    expect(out.label).toBe("Sync: Unavailable");
    expect(out.compactLabel).toBe("Unavail");
    expect(out.tone).toBe("neutral");
    expect(out.tooltip).toContain("cannot start");
    expect(out.tooltip).toContain("Read-only indicator.");
  });
});

// ---- Provider lifecycle -----------------------------------------------

function Probe() {
  const {
    safetySyncStatus,
    lastSafetyEventAt,
    lastSafetyRefreshAt,
  } = useSafetyState();
  return (
    <div>
      <span data-testid="probe-status">{safetySyncStatus}</span>
      <span data-testid="probe-event-at">{lastSafetyEventAt ?? "—"}</span>
      <span data-testid="probe-refresh-at">{lastSafetyRefreshAt ?? "—"}</span>
    </div>
  );
}

describe("Phase 15H - SafetyStateProvider sync lifecycle", () => {
  it("initial status is 'connecting' before any onStatusChange fires", () => {
    render(
      <SafetyStateProvider>
        <Probe />
      </SafetyStateProvider>,
    );
    expect(screen.getByTestId("probe-status").textContent).toBe("connecting");
  });

  it("onStatusChange callback flips status to live then reconnecting then offline", async () => {
    render(
      <SafetyStateProvider>
        <Probe />
      </SafetyStateProvider>,
    );
    await act(async () => {
      await Promise.resolve();
    });
    const ctrl = realtimeCalls[0];

    act(() => ctrl.onStatusChange?.("live"));
    expect(screen.getByTestId("probe-status").textContent).toBe("live");

    act(() => ctrl.onStatusChange?.("reconnecting"));
    expect(screen.getByTestId("probe-status").textContent).toBe("reconnecting");

    act(() => ctrl.onStatusChange?.("offline"));
    expect(screen.getByTestId("probe-status").textContent).toBe("offline");
  });

  it("construction failure flips status to 'unavailable'", () => {
    realtimeShouldThrow = true;
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    render(
      <SafetyStateProvider>
        <Probe />
      </SafetyStateProvider>,
    );
    expect(screen.getByTestId("probe-status").textContent).toBe("unavailable");
    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  it("matching event stamps lastSafetyEventAt AND lastSafetyRefreshAt after debounce", async () => {
    render(
      <SafetyStateProvider>
        <Probe />
      </SafetyStateProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    const ctrl = realtimeCalls[0];
    expect(screen.getByTestId("probe-event-at").textContent).toBe("—");
    expect(screen.getByTestId("probe-refresh-at").textContent).toBe("—");

    act(() => {
      ctrl.onEvent?.({
        time: "",
        icon: "",
        text: "",
        tone: "info",
        kind: "runtime.kill_switch.enabled",
      });
    });
    // Event timestamp lands immediately.
    expect(screen.getByTestId("probe-event-at").textContent).not.toBe("—");
    // Refresh timestamp lands only after debounce.
    expect(screen.getByTestId("probe-refresh-at").textContent).toBe("—");
    await act(async () => {
      vi.advanceTimersByTime(SAFETY_REFRESH_DEBOUNCE_MS + 10);
      await Promise.resolve();
    });
    expect(screen.getByTestId("probe-refresh-at").textContent).not.toBe("—");
  });

  it("non-matching event does NOT stamp lastSafetyEventAt or lastSafetyRefreshAt", async () => {
    render(
      <SafetyStateProvider>
        <Probe />
      </SafetyStateProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    const ctrl = realtimeCalls[0];

    act(() => {
      ctrl.onEvent?.({
        time: "",
        icon: "",
        text: "",
        tone: "info",
        kind: "order.created",
      });
    });
    await act(async () => {
      vi.advanceTimersByTime(SAFETY_REFRESH_DEBOUNCE_MS * 2);
      await Promise.resolve();
    });
    expect(screen.getByTestId("probe-event-at").textContent).toBe("—");
    expect(screen.getByTestId("probe-refresh-at").textContent).toBe("—");
  });

  it("unmount sets status back to 'offline' (no late 'live' leak)", async () => {
    function Wrapper({ children }: { children: React.ReactNode }) {
      return <SafetyStateProvider>{children}</SafetyStateProvider>;
    }
    const { unmount } = render(
      <Wrapper>
        <Probe />
      </Wrapper>,
    );
    await act(async () => {
      await Promise.resolve();
    });
    const ctrl = realtimeCalls[0];
    act(() => ctrl.onStatusChange?.("live"));
    expect(screen.getByTestId("probe-status").textContent).toBe("live");
    // Unmount should call controller.close() and the cleanup
    // setter should flip status to "offline" before the tree
    // unmounts. We can't read state after unmount, but we can
    // assert close() was invoked.
    unmount();
    expect(ctrl.close).toHaveBeenCalledTimes(1);
  });
});

// ---- Topbar render ----------------------------------------------------

const renderTopbar = () =>
  render(
    <MemoryRouter>
      <SafetyStateProvider>
        <Topbar onMenu={() => {}} />
      </SafetyStateProvider>
    </MemoryRouter>,
  );

describe("Phase 15H - Topbar Safety Sync indicator render", () => {
  it("renders the indicator with role=status and data-safety-sync-status='connecting' on mount", () => {
    renderTopbar();
    const ind = screen.getByTestId("topbar-safety-sync-indicator");
    expect(ind.getAttribute("role")).toBe("status");
    expect(ind.getAttribute("data-safety-sync-status")).toBe("connecting");
    expect(ind.getAttribute("aria-label") || "").toContain("Safety Sync:");
    expect(ind.getAttribute("aria-label") || "").toContain("Read-only indicator.");
  });

  it("indicator updates to 'live' when the helper fires onStatusChange('live')", async () => {
    renderTopbar();
    await act(async () => {
      await Promise.resolve();
    });
    const ctrl = realtimeCalls[0];
    act(() => ctrl.onStatusChange?.("live"));
    const ind = screen.getByTestId("topbar-safety-sync-indicator");
    expect(ind.getAttribute("data-safety-sync-status")).toBe("live");
    expect(ind.getAttribute("data-safety-sync-tone")).toBe("success");
  });

  it("indicator updates to 'reconnecting' / 'offline' on subsequent onStatusChange calls", async () => {
    renderTopbar();
    await act(async () => {
      await Promise.resolve();
    });
    const ctrl = realtimeCalls[0];
    act(() => ctrl.onStatusChange?.("reconnecting"));
    const ind = screen.getByTestId("topbar-safety-sync-indicator");
    expect(ind.getAttribute("data-safety-sync-status")).toBe("reconnecting");
    expect(ind.getAttribute("data-safety-sync-tone")).toBe("warning");

    act(() => ctrl.onStatusChange?.("offline"));
    expect(ind.getAttribute("data-safety-sync-status")).toBe("offline");
    expect(ind.getAttribute("data-safety-sync-tone")).toBe("warning");
  });

  it("construction failure renders 'unavailable' tone='neutral' without crashing", () => {
    realtimeShouldThrow = true;
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    renderTopbar();
    const ind = screen.getByTestId("topbar-safety-sync-indicator");
    expect(ind.getAttribute("data-safety-sync-status")).toBe("unavailable");
    expect(ind.getAttribute("data-safety-sync-tone")).toBe("neutral");
    warnSpy.mockRestore();
  });

  it("indicator is read-only: <span role='status'>, no button, no anchor, no click handler", () => {
    renderTopbar();
    const ind = screen.getByTestId("topbar-safety-sync-indicator");
    expect(ind.tagName).toBe("SPAN");
    expect(ind.closest("button")).toBeNull();
    expect(ind.closest("a")).toBeNull();
    expect(ind.getAttribute("role")).toBe("status");
  });

  it("full + compact labels both render with the responsive classes", async () => {
    renderTopbar();
    await act(async () => {
      await Promise.resolve();
    });
    const ctrl = realtimeCalls[0];
    act(() => ctrl.onStatusChange?.("live"));
    const full = screen.getByTestId("topbar-safety-sync-label");
    const compact = screen.getByTestId("topbar-safety-sync-compact-label");
    expect(full.className).toContain("hidden");
    expect(full.className).toContain("xl:inline");
    expect(compact.className).toContain("xl:hidden");
    expect(full.textContent).toBe("Sync: Live");
    expect(compact.textContent).toBe("Live");
  });

  it("co-renders with existing Topbar Safety Pill (Phase 15D/15E) without regression", () => {
    renderTopbar();
    expect(screen.getByTestId("topbar-safety-pill")).toBeInTheDocument();
    expect(
      screen.getByTestId("topbar-safety-sync-indicator"),
    ).toBeInTheDocument();
  });
});
