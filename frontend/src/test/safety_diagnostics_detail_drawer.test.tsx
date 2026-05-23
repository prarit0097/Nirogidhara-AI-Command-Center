/**
 * Phase 15J - tests for the Safety Diagnostics Detail Drawer.
 *
 * Covers:
 *   - Helpers (syncVisual, endpointVisual, formatTimestamp,
 *     deriveRefreshSourceLabel, buildErrorSummary) all return
 *     sanitised data.
 *   - "View details" button renders in the panel.
 *   - Clicking the button opens the modal; modal title + the
 *     read-only guarantee sentence both visible.
 *   - Modal shows the four sync rows + three endpoint rows.
 *   - Empty timestamp fallbacks render "Never" / "No event seen yet"
 *     / "Not tracked".
 *   - When endpoints are healthy, the Safe error summary shows
 *     "No safety errors detected."
 *   - When endpoints error, the summary lists short sanitised
 *     labels — never raw stack traces, response bodies, or tokens.
 *   - Close button closes the modal.
 *   - Opening + closing the modal never triggers a POST/PATCH/DELETE
 *     api call (asserted by mocking every api method on the
 *     services barrel and counting calls).
 *   - Sensitive-data grep: rendered DOM never contains tokens,
 *     phones, emails, addresses, payment URLs, system_policy,
 *     instruction_payload, raw_payload, raw_response.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";
import { SafetyStateProvider } from "@/context/SafetyStateContext";
import { SafetyDiagnosticsPanel } from "@/components/settings/SafetyDiagnosticsPanel";
import {
  SafetyDiagnosticsDetailModal,
  __testing__,
} from "@/components/settings/SafetyDiagnosticsDetailModal";

// ---- api + realtime mocks ---------------------------------------------
// Phase 15J - vi.mock is hoisted above top-level identifiers, so we
// declare the fns inside the factory and re-export the mocked api
// via `import { api } from "@/services/api"` below.

vi.mock("@/services/api", () => ({
  api: {
    getSaasRuntimeLiveGateKillSwitch: vi.fn(),
    getAiSandboxModeStatus: vi.fn(),
    getDirectorBriefingSidebarStatus: vi.fn(),
    // The read-only guarantee asserts these mutation methods are
    // NEVER called by anything the drawer does. Spied via the
    // imported `api` below.
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
const apiMock = api as unknown as {
  getSaasRuntimeLiveGateKillSwitch: ReturnType<typeof vi.fn>;
  getAiSandboxModeStatus: ReturnType<typeof vi.fn>;
  getDirectorBriefingSidebarStatus: ReturnType<typeof vi.fn>;
  postSaasRuntimeLiveGateKillSwitch: ReturnType<typeof vi.fn>;
  postAiSandboxModeAction: ReturnType<typeof vi.fn>;
};

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
  apiMock.getSaasRuntimeLiveGateKillSwitch.mockResolvedValue(killRunning);
  apiMock.getAiSandboxModeStatus.mockResolvedValue(sandboxOff);
  apiMock.getDirectorBriefingSidebarStatus.mockResolvedValue(briefingReady);
});

afterEach(() => {
  vi.useRealTimers();
});

// ---- Pure helpers ----------------------------------------------------

describe("Phase 15J - helpers", () => {
  it("syncVisual covers all 5 SafetySyncStatus values", () => {
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

  it("endpointVisual covers OK / Loading / Error", () => {
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

  it("formatTimestamp handles null / invalid / valid ISO", () => {
    expect(__testing__.formatTimestamp(null, "Never")).toBe("Never");
    expect(__testing__.formatTimestamp("nope", "Never")).toBe("Never");
    const out = __testing__.formatTimestamp("2026-05-23T06:00:00Z", "Never");
    expect(out).not.toBe("Never");
    expect(out.length).toBeGreaterThan(0);
  });

  it("deriveRefreshSourceLabel covers initial_load / audit_event / unknown", () => {
    expect(
      __testing__.deriveRefreshSourceLabel("2026-05-23T06:00:00Z", null),
    ).toBe("initial_load");
    expect(
      __testing__.deriveRefreshSourceLabel(
        "2026-05-23T06:00:01Z",
        "2026-05-23T06:00:00Z",
      ),
    ).toBe("audit_event");
    expect(__testing__.deriveRefreshSourceLabel(null, null)).toBe("unknown");
    // Event without refresh -> unknown (refresh hasn't landed yet).
    expect(
      __testing__.deriveRefreshSourceLabel(null, "2026-05-23T06:00:00Z"),
    ).toBe("unknown");
  });

  it("buildErrorSummary surfaces only short sanitised labels", () => {
    const out = __testing__.buildErrorSummary({
      killSwitchStatus: "error",
      sandboxStatus: "ok",
      briefingStatus: "error",
      safetySyncStatus: "offline",
    });
    expect(out).toEqual([
      "Kill switch endpoint failed",
      "Briefing endpoint failed",
      "Safety sync stream unavailable",
    ]);
    for (const label of out) {
      expect(label.length).toBeLessThan(80);
      expect(label).not.toContain("Error:");
      expect(label).not.toContain("Bearer");
      expect(label).not.toContain("sk-");
      expect(label).not.toContain("Traceback");
    }
  });

  it("buildErrorSummary returns empty list when everything is healthy", () => {
    expect(
      __testing__.buildErrorSummary({
        killSwitchStatus: "ok",
        sandboxStatus: "ok",
        briefingStatus: "ok",
        safetySyncStatus: "live",
      }),
    ).toEqual([]);
  });
});

// ---- View details trigger --------------------------------------------

describe("Phase 15J - View details trigger", () => {
  it("renders the 'View details' button on the SafetyDiagnosticsPanel", () => {
    render(
      <SafetyStateProvider>
        <SafetyDiagnosticsPanel />
      </SafetyStateProvider>,
    );
    expect(
      screen.getByTestId("safety-diagnostics-view-details"),
    ).toBeInTheDocument();
  });

  it("clicking the button opens the detail modal with the expected title", () => {
    render(
      <SafetyStateProvider>
        <SafetyDiagnosticsPanel />
      </SafetyStateProvider>,
    );
    expect(
      screen.queryByTestId("safety-diagnostics-detail-modal"),
    ).toBeNull();
    fireEvent.click(screen.getByTestId("safety-diagnostics-view-details"));
    expect(
      screen.getByTestId("safety-diagnostics-detail-modal"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("safety-diagnostics-detail-title").textContent,
    ).toBe("Safety Diagnostics Details");
  });

  it("opening + closing the modal never invokes a POST/PATCH/DELETE api method", () => {
    render(
      <SafetyStateProvider>
        <SafetyDiagnosticsPanel />
      </SafetyStateProvider>,
    );
    const initialCounts = {
      ks: apiMock.postSaasRuntimeLiveGateKillSwitch.mock.calls.length,
      sb: apiMock.postAiSandboxModeAction.mock.calls.length,
    };
    fireEvent.click(screen.getByTestId("safety-diagnostics-view-details"));
    fireEvent.click(screen.getByTestId("safety-diagnostics-detail-close"));
    expect(
      apiMock.postSaasRuntimeLiveGateKillSwitch.mock.calls.length,
    ).toBe(initialCounts.ks);
    expect(
      apiMock.postAiSandboxModeAction.mock.calls.length,
    ).toBe(initialCounts.sb);
  });
});

// ---- Standalone modal content (driven directly) -----------------------

function renderModal() {
  return render(
    <SafetyStateProvider>
      <SafetyDiagnosticsDetailModal open={true} onOpenChange={() => {}} />
    </SafetyStateProvider>,
  );
}

describe("Phase 15J - modal content (initial / loading state)", () => {
  it("renders the four sync rows + three endpoint rows + read-only note", () => {
    renderModal();
    for (const testid of [
      "detail-sync-status",
      "detail-last-event",
      "detail-last-refresh",
      "detail-refresh-source",
      "detail-reconnect-attempts",
      "detail-kill-switch",
      "detail-sandbox",
      "detail-briefing",
      "safety-diagnostics-detail-readonly-note",
    ]) {
      expect(screen.getByTestId(testid)).toBeInTheDocument();
    }
  });

  it("initial state: sync=Connecting, last event=No event seen yet, last refresh=Never, refresh source=Unknown, reconnect=Not tracked", () => {
    renderModal();
    expect(
      screen.getByTestId("detail-sync-status-value").textContent,
    ).toContain("Connecting");
    expect(
      screen.getByTestId("detail-last-event-value").textContent,
    ).toContain("No event seen yet");
    expect(
      screen.getByTestId("detail-last-refresh-value").textContent,
    ).toContain("Never");
    expect(
      screen.getByTestId("detail-refresh-source-value").textContent,
    ).toContain("Unknown");
    expect(
      screen.getByTestId("detail-reconnect-attempts-value").textContent,
    ).toContain("Not tracked");
  });

  it("error summary shows 'No safety errors detected.' when everything is healthy after fetches settle", async () => {
    renderModal();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(
      screen.getByTestId("detail-errors-empty").textContent,
    ).toContain("No safety errors detected.");
  });

  it("read-only guarantee sentence is present verbatim", () => {
    renderModal();
    const note = screen.getByTestId("safety-diagnostics-detail-readonly-note");
    expect(note.textContent || "").toContain("read-only");
    expect(note.textContent || "").toContain("does not resume AI");
    expect(note.textContent || "").toContain("create audit events");
  });
});

// ---- Error path: error summary --------------------------------------

describe("Phase 15J - modal content (error path)", () => {
  it("lists 'Kill switch endpoint failed' when the kill-switch GET errors, leaves sandbox + briefing OK", async () => {
    apiMock.getSaasRuntimeLiveGateKillSwitch.mockRejectedValue(
      new Error("HTTP 500"),
    );
    const consoleErrSpy = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});
    renderModal();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(
      screen.getByTestId("detail-kill-switch-value").textContent,
    ).toContain("Error");
    expect(
      screen.getByTestId("detail-sandbox-value").textContent,
    ).toContain("OK");
    expect(
      screen.getByTestId("detail-briefing-value").textContent,
    ).toContain("OK");

    const list = screen.getByTestId("detail-errors-list");
    expect(list.textContent || "").toContain("Kill switch endpoint failed");
    expect(list.textContent || "").not.toContain("HTTP 500");
    expect(list.textContent || "").not.toContain("Error:");

    consoleErrSpy.mockRestore();
  });

  it("does not render any forbidden secret / token / phone / payload string anywhere", async () => {
    renderModal();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
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

// ---- Close behavior --------------------------------------------------

describe("Phase 15J - close behavior", () => {
  it("clicking the Close button fires onOpenChange(false)", () => {
    const onOpenChange = vi.fn();
    render(
      <SafetyStateProvider>
        <SafetyDiagnosticsDetailModal open={true} onOpenChange={onOpenChange} />
      </SafetyStateProvider>,
    );
    fireEvent.click(screen.getByTestId("safety-diagnostics-detail-close"));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
