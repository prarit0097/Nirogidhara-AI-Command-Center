/**
 * Phase 15L - tests for the Safety Diagnostics Manual Refresh button.
 *
 * Covers:
 *   - Panel renders the "Refresh status" button next to "View details".
 *   - Clicking the panel button calls the three safety GET endpoints
 *     exactly once (Promise.allSettled wave).
 *   - Clicking the panel button never invokes a POST/PATCH/DELETE
 *     api method.
 *   - Button disables + shows "Refreshing…" label while in flight.
 *   - lastRefreshSource flips to "manual_refresh" after a manual
 *     refresh.
 *   - Concurrent clicks while a refresh is in flight return the
 *     same promise (idempotency) — only one wave of GETs fires.
 *   - Detail drawer footer renders a second "Refresh status"
 *     button bound to the same shared callback.
 *   - Drawer's "Refresh source" row updates to "Manual refresh"
 *     after a manual refresh.
 *   - Session-expiry path (Phase 15K) — a 401 during manual
 *     refresh does NOT fire a per-widget toast (suppressed by
 *     the safeFetch global dedupe), endpoint statuses correctly
 *     flip to "Error", panel does NOT claim OK.
 *   - Sensitive-data grep: rendered DOM never contains tokens /
 *     phones / secrets / payload keys.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";
import { SafetyStateProvider } from "@/context/SafetyStateContext";
import { SafetyDiagnosticsPanel } from "@/components/settings/SafetyDiagnosticsPanel";
import { SafetyDiagnosticsDetailModal } from "@/components/settings/SafetyDiagnosticsDetailModal";

// ---- api + realtime mocks ---------------------------------------------

vi.mock("@/services/api", () => ({
  api: {
    getSaasRuntimeLiveGateKillSwitch: vi.fn(),
    getAiSandboxModeStatus: vi.fn(),
    getDirectorBriefingSidebarStatus: vi.fn(),
    // The read-only guarantee asserts these mutation methods are
    // NEVER called by anything the panel/drawer does.
    postSaasRuntimeLiveGateKillSwitch: vi.fn(),
    postAiSandboxModeAction: vi.fn(),
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
  latestSnapshotAt: "2026-05-26T06:00:00Z",
  ageMinutes: 10,
  healthScore: 80,
  tier: "good",
  targetRoute: "/ceo-ai",
};

beforeEach(() => {
  vi.clearAllMocks();
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

async function flushMicrotasks(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

// ---- Panel button ----------------------------------------------------

describe("Phase 15L - Safety Diagnostics Panel 'Refresh status' button", () => {
  it("renders the 'Refresh status' button next to 'View details'", async () => {
    render(
      <SafetyStateProvider>
        <SafetyDiagnosticsPanel />
      </SafetyStateProvider>,
    );
    await flushMicrotasks();
    expect(
      screen.getByTestId("safety-diagnostics-refresh-status"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("safety-diagnostics-view-details"),
    ).toBeInTheDocument();
  });

  it("clicking the button re-fires each of the three safety GET endpoints", async () => {
    render(
      <SafetyStateProvider>
        <SafetyDiagnosticsPanel />
      </SafetyStateProvider>,
    );
    await flushMicrotasks();
    const ksMock = api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<
      typeof vi.fn
    >;
    const sbMock = api.getAiSandboxModeStatus as unknown as ReturnType<
      typeof vi.fn
    >;
    const brMock = api.getDirectorBriefingSidebarStatus as unknown as ReturnType<
      typeof vi.fn
    >;
    const initialKs = ksMock.mock.calls.length;
    const initialSb = sbMock.mock.calls.length;
    const initialBr = brMock.mock.calls.length;

    fireEvent.click(screen.getByTestId("safety-diagnostics-refresh-status"));
    await flushMicrotasks();

    expect(ksMock.mock.calls.length).toBe(initialKs + 1);
    expect(sbMock.mock.calls.length).toBe(initialSb + 1);
    expect(brMock.mock.calls.length).toBe(initialBr + 1);
  });

  it("clicking the button never invokes a POST/PATCH/DELETE api method", async () => {
    render(
      <SafetyStateProvider>
        <SafetyDiagnosticsPanel />
      </SafetyStateProvider>,
    );
    await flushMicrotasks();
    fireEvent.click(screen.getByTestId("safety-diagnostics-refresh-status"));
    await flushMicrotasks();
    expect(
      (api.postSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<
        typeof vi.fn
      >).mock.calls.length,
    ).toBe(0);
    expect(
      (api.postAiSandboxModeAction as unknown as ReturnType<typeof vi.fn>).mock
        .calls.length,
    ).toBe(0);
  });

  it("button disables + label flips to 'Refreshing…' while a refresh is in flight", async () => {
    render(
      <SafetyStateProvider>
        <SafetyDiagnosticsPanel />
      </SafetyStateProvider>,
    );
    // Let the initial mount fetch resolve normally so refreshing
    // is false to start.
    await flushMicrotasks();

    // Make the NEXT kill-switch GET (the manual refresh) hang so
    // the in-flight state persists long enough for the assertion.
    let resolveKs: ((value: typeof killRunning) => void) | null = null;
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockImplementationOnce(
      () =>
        new Promise<typeof killRunning>((resolve) => {
          resolveKs = resolve;
        }),
    );

    fireEvent.click(screen.getByTestId("safety-diagnostics-refresh-status"));
    await flushMicrotasks();

    const button = screen.getByTestId("safety-diagnostics-refresh-status");
    expect(button.hasAttribute("disabled")).toBe(true);
    expect(
      screen.getByTestId("safety-diagnostics-refresh-status-label").textContent,
    ).toContain("Refreshing");

    // Release the manual-refresh promise so finally() runs.
    await act(async () => {
      if (resolveKs) resolveKs(killRunning);
      await Promise.resolve();
      await Promise.resolve();
    });
  });

  it("concurrent clicks while a refresh is in flight coalesce into ONE wave of GETs", async () => {
    let resolveKs: ((value: typeof killRunning) => void) | null = null;
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(killRunning); // initial mount fetch
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockImplementationOnce(
      () => Promise.resolve(killRunning), // initial mount
    );

    render(
      <SafetyStateProvider>
        <SafetyDiagnosticsPanel />
      </SafetyStateProvider>,
    );
    await flushMicrotasks();

    // Next click hangs.
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockImplementationOnce(
      () =>
        new Promise<typeof killRunning>((resolve) => {
          resolveKs = resolve;
        }),
    );

    const ksMock = api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<
      typeof vi.fn
    >;
    const startCount = ksMock.mock.calls.length;
    const btn = screen.getByTestId("safety-diagnostics-refresh-status");
    fireEvent.click(btn);
    // 4 rapid concurrent clicks while the first is still pending.
    fireEvent.click(btn);
    fireEvent.click(btn);
    fireEvent.click(btn);
    fireEvent.click(btn);
    await flushMicrotasks();

    // Exactly one new wave (1 GET) fired — not 5.
    expect(ksMock.mock.calls.length - startCount).toBe(1);

    await act(async () => {
      if (resolveKs) resolveKs(killRunning);
      await Promise.resolve();
      await Promise.resolve();
    });
  });
});

// ---- Detail drawer ---------------------------------------------------

function renderDrawer() {
  return render(
    <SafetyStateProvider>
      <SafetyDiagnosticsDetailModal open={true} onOpenChange={() => {}} />
    </SafetyStateProvider>,
  );
}

describe("Phase 15L - Safety Diagnostics Detail Drawer 'Refresh status' button", () => {
  it("drawer footer renders a 'Refresh status' button bound to the same shared callback", async () => {
    renderDrawer();
    await flushMicrotasks();
    expect(
      screen.getByTestId("safety-diagnostics-detail-refresh"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("safety-diagnostics-detail-close"),
    ).toBeInTheDocument();
  });

  it("clicking the drawer button re-fires the three GETs and updates the Refresh source row to 'Manual refresh'", async () => {
    renderDrawer();
    await flushMicrotasks();
    // Initial state — provider's first fetch ran on mount.
    // After the initial fetch settles, source is "initial_load".
    expect(
      screen.getByTestId("detail-refresh-source-value").textContent,
    ).toContain("Initial load");

    const ksMock = api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<
      typeof vi.fn
    >;
    const initialKs = ksMock.mock.calls.length;
    fireEvent.click(screen.getByTestId("safety-diagnostics-detail-refresh"));
    await flushMicrotasks();
    expect(ksMock.mock.calls.length).toBe(initialKs + 1);
    expect(
      screen.getByTestId("detail-refresh-source-value").textContent,
    ).toContain("Manual refresh");
  });

  it("drawer Refresh status button never invokes a POST/PATCH/DELETE api method", async () => {
    renderDrawer();
    await flushMicrotasks();
    fireEvent.click(screen.getByTestId("safety-diagnostics-detail-refresh"));
    await flushMicrotasks();
    expect(
      (api.postSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<
        typeof vi.fn
      >).mock.calls.length,
    ).toBe(0);
    expect(
      (api.postAiSandboxModeAction as unknown as ReturnType<typeof vi.fn>).mock
        .calls.length,
    ).toBe(0);
  });

  it("drawer does not render any forbidden secret / token / phone / payload string", async () => {
    renderDrawer();
    await flushMicrotasks();
    const text =
      screen.getByTestId("safety-diagnostics-detail-modal").textContent || "";
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
      "Traceback",
    ]) {
      expect(text).not.toContain(forbidden);
    }
  });
});

// ---- Session-expiry path during manual refresh -----------------------

describe("Phase 15L - manual refresh respects Phase 15K session-expiry UX", () => {
  it("rejected GETs flip endpoint statuses to Error and never claim OK", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValueOnce(killRunning); // initial mount succeeds
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValueOnce(sandboxOff);
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValueOnce(briefingReady);

    render(
      <SafetyStateProvider>
        <SafetyDiagnosticsPanel />
      </SafetyStateProvider>,
    );
    await flushMicrotasks();

    // Next-wave rejects with auth-shaped error.
    const authErr = Object.assign(new Error("Session expired"), {
      isAuthError: true,
    });
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockRejectedValueOnce(authErr);
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockRejectedValueOnce(authErr);
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockRejectedValueOnce(authErr);

    const consoleErrSpy = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});

    fireEvent.click(screen.getByTestId("safety-diagnostics-refresh-status"));
    await flushMicrotasks();
    await flushMicrotasks();

    expect(
      screen.getByTestId("diagnostics-kill-switch-value").textContent,
    ).toContain("Error");
    expect(
      screen.getByTestId("diagnostics-sandbox-value").textContent,
    ).toContain("Error");
    expect(
      screen.getByTestId("diagnostics-briefing-value").textContent,
    ).toContain("Error");

    // Phase 15K - provider's inline isAuthError predicate
    // suppresses the three per-endpoint console.error calls,
    // so no [SafetyStateProvider] kill-switch / sandbox / briefing
    // load failed: messages appear for an auth-shaped rejection.
    const safetyErrorCalls = consoleErrSpy.mock.calls.filter((args) =>
      String(args[0]).includes("[SafetyStateProvider]"),
    );
    expect(safetyErrorCalls.length).toBe(0);

    consoleErrSpy.mockRestore();
  });
});
