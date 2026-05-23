/**
 * Phase 15G - tests for safety-state auto-refresh on audit events.
 *
 * Covers:
 *   - Helper allow-list (shouldRefreshOnEvent + the 3-prefix tuple).
 *   - Provider subscribes to connectAuditEvents exactly once on mount.
 *   - Allow-listed kill-switch event triggers exactly one fetchAll
 *     after the debounce window.
 *   - Allow-listed sandbox event triggers refresh.
 *   - Allow-listed ceo_orchestration.snapshot event triggers refresh.
 *   - Non-matching event does NOT trigger refresh.
 *   - Burst of 5 matching events within the debounce window
 *     coalesces into ONE fetchAll.
 *   - Unmount calls controller.close() and clears the pending
 *     debounce so no late refresh fires.
 *   - Stream construction error is swallowed (UI never crashes).
 *
 * The realtime helper is mocked end-to-end so the test never opens
 * a real WebSocket. The mock returns a controller that exposes the
 * captured onEvent / onError callbacks so the test can drive the
 * provider deterministically.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import {
  SafetyStateProvider,
  SAFETY_REFRESH_DEBOUNCE_MS,
  SAFETY_REFRESH_EVENT_PREFIXES,
  shouldRefreshOnEvent,
  useSafetyState,
} from "@/context/SafetyStateContext";

// ---- api mock ----------------------------------------------------------

vi.mock("@/services/api", () => ({
  api: {
    getSaasRuntimeLiveGateKillSwitch: vi.fn(),
    getAiSandboxModeStatus: vi.fn(),
    getDirectorBriefingSidebarStatus: vi.fn(),
  },
}));

// ---- realtime mock -----------------------------------------------------

const realtimeCalls: Array<{
  onEvent?: (event: unknown) => void;
  onError?: (err: unknown) => void;
  close: ReturnType<typeof vi.fn>;
}> = [];
let realtimeShouldThrow = false;

vi.mock("@/services/realtime", () => ({
  connectAuditEvents: vi.fn((opts: { onEvent?: (event: unknown) => void; onError?: (err: unknown) => void }) => {
    if (realtimeShouldThrow) {
      throw new Error("simulated stream construction failure");
    }
    const close = vi.fn();
    realtimeCalls.push({ onEvent: opts.onEvent, onError: opts.onError, close });
    return { close, isLive: () => false, url: "ws://test" };
  }),
}));

import { api } from "@/services/api";
import { connectAuditEvents } from "@/services/realtime";

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
  latestSnapshotAt: "2026-05-22T06:00:00Z",
  ageMinutes: 10,
  healthScore: 80,
  tier: "good",
  targetRoute: "/ceo-ai",
};

function Probe() {
  const { loading } = useSafetyState();
  return <span data-testid="probe-loading">{String(loading)}</span>;
}

beforeEach(() => {
  vi.clearAllMocks();
  // Fake only timers - leave microtasks (Promise.resolve, await)
  // alone so testing-library's waitFor still flushes naturally.
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  realtimeCalls.length = 0;
  realtimeShouldThrow = false;
  // Default-resolve all three GETs so the initial fetchAll settles.
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

// ---- Helper allow-list ----------------------------------------------------

describe("Phase 15G - shouldRefreshOnEvent helper", () => {
  it("exports the three documented prefix patterns", () => {
    expect(SAFETY_REFRESH_EVENT_PREFIXES).toEqual([
      "runtime.kill_switch.",
      "ai.sandbox.",
      "ceo_orchestration.snapshot.",
    ]);
  });

  it("matches kill-switch / sandbox / ceo_orchestration.snapshot kinds", () => {
    expect(shouldRefreshOnEvent({ time: "", icon: "", text: "", tone: "info", kind: "runtime.kill_switch.enabled" })).toBe(true);
    expect(shouldRefreshOnEvent({ time: "", icon: "", text: "", tone: "info", kind: "runtime.kill_switch.disabled" })).toBe(true);
    expect(shouldRefreshOnEvent({ time: "", icon: "", text: "", tone: "info", kind: "ai.sandbox.enabled" })).toBe(true);
    expect(shouldRefreshOnEvent({ time: "", icon: "", text: "", tone: "info", kind: "ai.sandbox.disabled" })).toBe(true);
    expect(shouldRefreshOnEvent({ time: "", icon: "", text: "", tone: "info", kind: "ceo_orchestration.snapshot.created" })).toBe(true);
  });

  it("does not match unrelated kinds, empty string, undefined, or events with no kind", () => {
    expect(shouldRefreshOnEvent({ time: "", icon: "", text: "", tone: "info", kind: "order.created" })).toBe(false);
    expect(shouldRefreshOnEvent({ time: "", icon: "", text: "", tone: "info", kind: "payment.received" })).toBe(false);
    expect(shouldRefreshOnEvent({ time: "", icon: "", text: "", tone: "info", kind: "whatsapp.message.sent" })).toBe(false);
    expect(shouldRefreshOnEvent({ time: "", icon: "", text: "", tone: "info", kind: "" })).toBe(false);
    expect(shouldRefreshOnEvent({ time: "", icon: "", text: "", tone: "info" })).toBe(false);
    expect(shouldRefreshOnEvent(null)).toBe(false);
    expect(shouldRefreshOnEvent(undefined)).toBe(false);
  });
});

// ---- Subscription lifecycle -------------------------------------------

describe("Phase 15G - SafetyStateProvider subscription lifecycle", () => {
  it("subscribes to connectAuditEvents exactly once on mount", async () => {
    render(
      <SafetyStateProvider>
        <Probe />
      </SafetyStateProvider>,
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(
      (connectAuditEvents as unknown as ReturnType<typeof vi.fn>).mock.calls
        .length,
    ).toBe(1);
    expect(realtimeCalls.length).toBe(1);
    expect(realtimeCalls[0].onEvent).toBeTypeOf("function");
  });

  it("unmount calls controller.close() and cancels pending debounce", async () => {
    const { unmount } = render(
      <SafetyStateProvider>
        <Probe />
      </SafetyStateProvider>,
    );
    await act(async () => {
      await Promise.resolve();
    });
    const closeMock = realtimeCalls[0].close;

    // Dispatch a matching event so the debounce timer is armed.
    act(() => {
      realtimeCalls[0].onEvent?.({
        time: "",
        icon: "",
        text: "",
        tone: "info",
        kind: "runtime.kill_switch.enabled",
      });
    });

    // Unmount before debounce window elapses.
    unmount();
    expect(closeMock).toHaveBeenCalledTimes(1);

    // Initial calls = 1 per endpoint. Advancing the timer must NOT
    // trigger a second fetchAll because the debounce was cancelled
    // on unmount.
    const initialKsCalls = (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.length;
    act(() => {
      vi.advanceTimersByTime(SAFETY_REFRESH_DEBOUNCE_MS + 100);
    });
    expect(
      (api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>)
        .mock.calls.length,
    ).toBe(initialKsCalls);
  });

  it("survives stream construction failure (no UI crash)", async () => {
    realtimeShouldThrow = true;
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(() =>
      render(
        <SafetyStateProvider>
          <Probe />
        </SafetyStateProvider>,
      ),
    ).not.toThrow();
    await act(async () => {
      await Promise.resolve();
    });
    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
  });
});

// ---- Refresh on matching events ---------------------------------------

describe("Phase 15G - matching events trigger debounced refresh", () => {
  async function setupProvider() {
    render(
      <SafetyStateProvider>
        <Probe />
      </SafetyStateProvider>,
    );
    // Flush microtasks for the initial Promise.allSettled. With
    // fake timers, testing-library's waitFor() can't poll, so we
    // flush manually. Two flushes are enough since fetchAll's
    // resolved-mock chain only has setLoading(true) -> await ->
    // setStates -> setLoading(false).
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByTestId("probe-loading").textContent).toBe("false");
    return realtimeCalls[0];
  }

  it("runtime.kill_switch.enabled triggers exactly one refresh after the debounce", async () => {
    const ctrl = await setupProvider();
    const initial = (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.length;
    act(() => {
      ctrl.onEvent?.({
        time: "",
        icon: "",
        text: "",
        tone: "info",
        kind: "runtime.kill_switch.enabled",
      });
    });
    // Before debounce elapses - still at the initial call count.
    expect(
      (api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>)
        .mock.calls.length,
    ).toBe(initial);
    await act(async () => {
      vi.advanceTimersByTime(SAFETY_REFRESH_DEBOUNCE_MS + 10);
      await Promise.resolve();
    });
    expect(
      (api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>)
        .mock.calls.length,
    ).toBe(initial + 1);
  });

  it("ai.sandbox.enabled triggers exactly one refresh after the debounce", async () => {
    const ctrl = await setupProvider();
    const initial = (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.length;
    act(() => {
      ctrl.onEvent?.({
        time: "",
        icon: "",
        text: "",
        tone: "info",
        kind: "ai.sandbox.enabled",
      });
    });
    await act(async () => {
      vi.advanceTimersByTime(SAFETY_REFRESH_DEBOUNCE_MS + 10);
      await Promise.resolve();
    });
    expect(
      (api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>).mock
        .calls.length,
    ).toBe(initial + 1);
  });

  it("ceo_orchestration.snapshot.created triggers exactly one refresh after the debounce", async () => {
    const ctrl = await setupProvider();
    const initial = (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.length;
    act(() => {
      ctrl.onEvent?.({
        time: "",
        icon: "",
        text: "",
        tone: "info",
        kind: "ceo_orchestration.snapshot.created",
      });
    });
    await act(async () => {
      vi.advanceTimersByTime(SAFETY_REFRESH_DEBOUNCE_MS + 10);
      await Promise.resolve();
    });
    expect(
      (api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>)
        .mock.calls.length,
    ).toBe(initial + 1);
  });

  it("non-matching event does NOT trigger a refresh", async () => {
    const ctrl = await setupProvider();
    const initial = (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.length;
    act(() => {
      ctrl.onEvent?.({
        time: "",
        icon: "",
        text: "",
        tone: "info",
        kind: "order.created",
      });
      ctrl.onEvent?.({
        time: "",
        icon: "",
        text: "",
        tone: "info",
        kind: "whatsapp.message.sent",
      });
      ctrl.onEvent?.({
        time: "",
        icon: "",
        text: "",
        tone: "info",
        kind: "payment.received",
      });
    });
    await act(async () => {
      vi.advanceTimersByTime(SAFETY_REFRESH_DEBOUNCE_MS * 3);
      await Promise.resolve();
    });
    expect(
      (api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>)
        .mock.calls.length,
    ).toBe(initial);
  });

  it("burst of 5 matching events inside the debounce window coalesces to ONE refresh", async () => {
    const ctrl = await setupProvider();
    const initial = (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.length;
    act(() => {
      ctrl.onEvent?.({ time: "", icon: "", text: "", tone: "info", kind: "runtime.kill_switch.enabled" });
      ctrl.onEvent?.({ time: "", icon: "", text: "", tone: "info", kind: "runtime.kill_switch.disabled" });
      ctrl.onEvent?.({ time: "", icon: "", text: "", tone: "info", kind: "ai.sandbox.enabled" });
      ctrl.onEvent?.({ time: "", icon: "", text: "", tone: "info", kind: "ai.sandbox.disabled" });
      ctrl.onEvent?.({ time: "", icon: "", text: "", tone: "info", kind: "ceo_orchestration.snapshot.created" });
    });
    await act(async () => {
      vi.advanceTimersByTime(SAFETY_REFRESH_DEBOUNCE_MS + 10);
      await Promise.resolve();
    });
    // Exactly +1 call per endpoint - not +5.
    expect(
      (api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>)
        .mock.calls.length,
    ).toBe(initial + 1);
    expect(
      (api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>).mock
        .calls.length,
    ).toBe(initial + 1);
    expect(
      (api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>)
        .mock.calls.length,
    ).toBe(initial + 1);
  });
});
