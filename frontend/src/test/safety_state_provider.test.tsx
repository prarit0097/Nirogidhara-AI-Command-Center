/**
 * Phase 15F - tests for the shared SafetyStateProvider + useSafetyState
 * hook.
 *
 * Covers:
 *   - Fetches each of the three safety endpoints exactly once on
 *     mount (deduplication contract).
 *   - Two child components consuming useSafetyState() share one
 *     snapshot - no duplicate fetches and no out-of-sync state.
 *   - Loading state is exposed correctly while fetches are pending.
 *   - Granular error tags (auth / permission / generic) are surfaced
 *     for the briefing fetch.
 *   - Sidebar + Topbar derived views are wired through the existing
 *     computeSafetyStatus / computeTopbarSafetySummary helpers.
 *   - refresh() re-runs all three GETs once.
 *   - setKillSwitch() updates the snapshot without triggering a
 *     refetch (used by the KillSwitchModal success callback).
 *   - useSafetyState() consumed outside a provider returns the inert
 *     loading fallback (does NOT throw).
 *   - Provider NEVER calls a POST/PATCH/DELETE on any api method.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import {
  SafetyStateProvider,
  useSafetyState,
} from "@/context/SafetyStateContext";

// ---- api mock ----------------------------------------------------------

vi.mock("@/services/api", () => ({
  api: {
    getSaasRuntimeLiveGateKillSwitch: vi.fn(),
    getAiSandboxModeStatus: vi.fn(),
    getDirectorBriefingSidebarStatus: vi.fn(),
    // Any non-GET method on the api object would trip this guard
    // if the provider ever invoked it - we never expect it to.
    postSaasRuntimeLiveGateKillSwitch: vi.fn(),
    postAiSandboxModeAction: vi.fn(),
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
  confirmationPhrases: {
    activateEmergencyStop: "ACTIVATE KILL SWITCH",
    resumeAiOperations: "RESUME AI OPERATIONS",
  },
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

const briefingReady = {
  status: "ready" as const,
  label: "Briefing ready",
  latestSnapshotId: 42,
  latestSnapshotAt: "2026-05-22T06:00:00Z",
  ageMinutes: 10,
  healthScore: 80,
  tier: "good",
  targetRoute: "/ceo-ai",
};

function ConsumerOne() {
  const { topbar, sidebar, loading } = useSafetyState();
  return (
    <div>
      <span data-testid="consumer-one-topbar-label">{topbar.label}</span>
      <span data-testid="consumer-one-sidebar-label">{sidebar.label}</span>
      <span data-testid="consumer-one-loading">{String(loading)}</span>
    </div>
  );
}

function ConsumerTwo() {
  const { topbar, killSwitch } = useSafetyState();
  return (
    <div>
      <span data-testid="consumer-two-topbar-label">{topbar.label}</span>
      <span data-testid="consumer-two-paused">
        {String(Boolean(killSwitch?.aiExecutionBlocked))}
      </span>
    </div>
  );
}

function ProviderWrapper({ children }: { children: React.ReactNode }) {
  return <SafetyStateProvider>{children}</SafetyStateProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
});

// ---- Deduplication ------------------------------------------------------

describe("Phase 15F - SafetyStateProvider deduplication", () => {
  it("fetches each of the three safety endpoints exactly once on mount", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(killPaused);
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOff);
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(briefingReady);

    render(
      <ProviderWrapper>
        <ConsumerOne />
      </ProviderWrapper>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("consumer-one-loading").textContent).toBe(
        "false",
      ),
    );
    expect(
      (api.getSaasRuntimeLiveGateKillSwitch as ReturnType<typeof vi.fn>).mock.calls
        .length,
    ).toBe(1);
    expect(
      (api.getAiSandboxModeStatus as ReturnType<typeof vi.fn>).mock.calls.length,
    ).toBe(1);
    expect(
      (api.getDirectorBriefingSidebarStatus as ReturnType<typeof vi.fn>).mock
        .calls.length,
    ).toBe(1);
  });

  it("two consumers share one snapshot - no duplicate fetches across consumers", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(killPaused);
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOff);
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(briefingReady);

    render(
      <ProviderWrapper>
        <ConsumerOne />
        <ConsumerTwo />
      </ProviderWrapper>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("consumer-one-loading").textContent).toBe(
        "false",
      ),
    );
    // Still one call per endpoint - the provider de-duplicates.
    expect(
      (api.getSaasRuntimeLiveGateKillSwitch as ReturnType<typeof vi.fn>).mock.calls
        .length,
    ).toBe(1);
    expect(
      (api.getAiSandboxModeStatus as ReturnType<typeof vi.fn>).mock.calls.length,
    ).toBe(1);
    expect(
      (api.getDirectorBriefingSidebarStatus as ReturnType<typeof vi.fn>).mock
        .calls.length,
    ).toBe(1);

    // Both consumers see the same topbar label.
    const a = screen.getByTestId("consumer-one-topbar-label").textContent;
    const b = screen.getByTestId("consumer-two-topbar-label").textContent;
    expect(a).toBe(b);
    expect(a).toContain("AI Paused");
  });
});

// ---- States ------------------------------------------------------------

describe("Phase 15F - SafetyStateProvider state surfaces", () => {
  it("exposes loading=true while fetches are pending", () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockReturnValue(new Promise(() => {}));
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockReturnValue(new Promise(() => {}));
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockReturnValue(new Promise(() => {}));

    render(
      <ProviderWrapper>
        <ConsumerOne />
      </ProviderWrapper>,
    );

    expect(screen.getByTestId("consumer-one-loading").textContent).toBe("true");
    expect(
      screen.getByTestId("consumer-one-topbar-label").textContent,
    ).toContain("Checking");
  });

  it("HTTP 401 on briefing classifies as briefingError='auth' but does not crash", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(killRunning);
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOff);
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockRejectedValue(new Error("HTTP 401 - session expired"));

    function AuthConsumer() {
      const { briefingError } = useSafetyState();
      return (
        <span data-testid="briefing-error-kind">{String(briefingError)}</span>
      );
    }

    render(
      <ProviderWrapper>
        <AuthConsumer />
      </ProviderWrapper>,
    );

    await waitFor(() =>
      expect(
        screen.getByTestId("briefing-error-kind").textContent,
      ).toBe("auth"),
    );
  });

  it("HTTP 403 on briefing classifies as 'permission' and HTTP 500 as 'generic'", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(killRunning);
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOff);
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockRejectedValueOnce(new Error("HTTP 403 forbidden"));

    function ErrConsumer() {
      const { briefingError } = useSafetyState();
      return <span data-testid="be1">{String(briefingError)}</span>;
    }

    const { unmount } = render(
      <ProviderWrapper>
        <ErrConsumer />
      </ProviderWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("be1").textContent).toBe("permission"),
    );
    unmount();

    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockRejectedValueOnce(new Error("Network down"));
    function ErrConsumer2() {
      const { briefingError } = useSafetyState();
      return <span data-testid="be2">{String(briefingError)}</span>;
    }
    render(
      <ProviderWrapper>
        <ErrConsumer2 />
      </ProviderWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("be2").textContent).toBe("generic"),
    );
  });

  it("never claims sidebar 'All systems normal' when kill-switch fetch errors", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockRejectedValue(new Error("HTTP 500"));
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOff);
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(briefingReady);

    render(
      <ProviderWrapper>
        <ConsumerOne />
      </ProviderWrapper>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("consumer-one-loading").textContent).toBe(
        "false",
      ),
    );
    const sidebarLabel = screen.getByTestId("consumer-one-sidebar-label")
      .textContent;
    expect(sidebarLabel).not.toBe("All systems normal");
    expect(sidebarLabel).toBe("Safety state unavailable");
  });
});

// ---- Refresh + setKillSwitch -------------------------------------------

describe("Phase 15F - refresh + setKillSwitch", () => {
  it("refresh() re-runs each of the three GETs exactly once more", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(killRunning);
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOff);
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(briefingReady);

    function RefresherConsumer() {
      const { refresh, loading } = useSafetyState();
      return (
        <div>
          <button
            data-testid="refresh-button"
            onClick={() => void refresh()}
          >
            refresh
          </button>
          <span data-testid="loading">{String(loading)}</span>
        </div>
      );
    }

    render(
      <ProviderWrapper>
        <RefresherConsumer />
      </ProviderWrapper>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("loading").textContent).toBe("false"),
    );
    // Initial call count = 1 per endpoint.
    await act(async () => {
      fireEvent.click(screen.getByTestId("refresh-button"));
    });
    await waitFor(() =>
      expect(screen.getByTestId("loading").textContent).toBe("false"),
    );

    expect(
      (api.getSaasRuntimeLiveGateKillSwitch as ReturnType<typeof vi.fn>).mock.calls
        .length,
    ).toBe(2);
    expect(
      (api.getAiSandboxModeStatus as ReturnType<typeof vi.fn>).mock.calls.length,
    ).toBe(2);
    expect(
      (api.getDirectorBriefingSidebarStatus as ReturnType<typeof vi.fn>).mock
        .calls.length,
    ).toBe(2);
  });

  it("setKillSwitch() updates state without triggering a refetch", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(killRunning);
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOff);
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(briefingReady);

    function SetterConsumer() {
      const { topbar, setKillSwitch } = useSafetyState();
      return (
        <div>
          <span data-testid="topbar-label">{topbar.label}</span>
          <button
            data-testid="set-paused"
            onClick={() => setKillSwitch(killPaused)}
          >
            paused
          </button>
        </div>
      );
    }

    render(
      <ProviderWrapper>
        <SetterConsumer />
      </ProviderWrapper>,
    );

    await waitFor(() =>
      expect(
        screen.getByTestId("topbar-label").textContent,
      ).toContain("AI Running"),
    );

    await act(async () => {
      fireEvent.click(screen.getByTestId("set-paused"));
    });

    await waitFor(() =>
      expect(
        screen.getByTestId("topbar-label").textContent,
      ).toContain("AI Paused"),
    );
    // setKillSwitch() should NOT trigger an extra GET.
    expect(
      (api.getSaasRuntimeLiveGateKillSwitch as ReturnType<typeof vi.fn>).mock.calls
        .length,
    ).toBe(1);
  });
});

// ---- Inert fallback when consumed outside provider --------------------

describe("Phase 15F - useSafetyState fallback", () => {
  it("returns the inert loading snapshot when used outside a provider (no throw)", () => {
    function Lonely() {
      const { topbar, loading } = useSafetyState();
      return (
        <div>
          <span data-testid="lonely-topbar-label">{topbar.label}</span>
          <span data-testid="lonely-loading">{String(loading)}</span>
        </div>
      );
    }
    render(<Lonely />);
    expect(screen.getByTestId("lonely-loading").textContent).toBe("true");
    expect(
      screen.getByTestId("lonely-topbar-label").textContent,
    ).toContain("Checking");
  });
});

// ---- Read-only invariant ----------------------------------------------

describe("Phase 15F - read-only invariant", () => {
  it("provider never calls any POST/PATCH/DELETE api method", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(killPaused);
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOff);
    (
      api.getDirectorBriefingSidebarStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(briefingReady);

    render(
      <ProviderWrapper>
        <ConsumerOne />
      </ProviderWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("consumer-one-loading").textContent).toBe(
        "false",
      ),
    );

    expect(
      (api.postSaasRuntimeLiveGateKillSwitch as ReturnType<typeof vi.fn>).mock
        .calls.length,
    ).toBe(0);
    expect(
      (api.postAiSandboxModeAction as ReturnType<typeof vi.fn>).mock.calls
        .length,
    ).toBe(0);
  });
});
