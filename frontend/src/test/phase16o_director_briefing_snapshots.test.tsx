import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return {
    ...actual,
    api: {
      getAiCopilotStatus: vi.fn(),
      getAiCopilotSuggestions: vi.fn(),
      generateAiCopilotSuggestion: vi.fn(),
      reviewAiCopilotSuggestion: vi.fn(),
      getAiActionQueue: vi.fn(),
      getAiActionSummary: vi.fn(),
      createAiActionFromSuggestion: vi.fn(),
      applyAiAction: vi.fn(),
      rejectAiAction: vi.fn(),
      cancelAiAction: vi.fn(),
      getAiWorkboard: vi.fn(),
      getAiWorkboardSummary: vi.fn(),
      getAiWorkboardDirectorAttention: vi.fn(),
      assignAiAction: vi.fn(),
      claimAiAction: vi.fn(),
      startAiAction: vi.fn(),
      blockAiAction: vi.fn(),
      unblockAiAction: vi.fn(),
      completeInternalAiAction: vi.fn(),
      reassignAiAction: vi.fn(),
      addAiActionNote: vi.fn(),
      getAiMyWork: vi.fn(),
      getAiMyWorkSummary: vi.fn(),
      getAiMyWorkPermissions: vi.fn(),
      getAiWorkboardAnalytics: vi.fn(),
      getAiDirectorBriefing: vi.fn(),
      // Phase 16O.
      getAiDirectorBriefingSnapshots: vi.fn(),
      getAiDirectorBriefingSnapshotSummary: vi.fn(),
      getAiDirectorBriefingSnapshot: vi.fn(),
      createAiDirectorBriefingSnapshot: vi.fn(),
      acknowledgeAiDirectorBriefingSnapshot: vi.fn(),
      markAiDirectorBriefingSnapshotNeedsFollowUp: vi.fn(),
      archiveAiDirectorBriefingSnapshot: vi.fn(),
      addAiDirectorBriefingSnapshotNote: vi.fn(),
      // Representative provider/business methods — must never be called here.
      createImportOrder: vi.fn(),
      transitionPilotTask: vi.fn(),
    },
  };
});

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

import AiCopilot from "@/pages/AiCopilot";
import { api } from "@/services/api";

const STATUS = {
  aiPaused: true, sandboxOn: false, syncLive: true,
  providerLiveActionsLocked: true, liveAutonomousExecutionLocked: true,
  phase15ShellFrozen: true, aiMode: "mock" as const,
  liveProviderStatus: "unavailable" as const, aiProvider: "disabled",
  humanApprovalRequired: true, noProviderCallMade: true, phase: "16I",
};

const MY_PERMISSIONS = {
  isAdmin: true, canViewWorkboard: true, canAssign: true, canReassign: true,
  canManageMembership: true, departments: [],
  providerActionsLocked: true, liveAutonomousExecutionLocked: true, phase: "16L",
};

const BRIEFING = {
  briefingStatus: { generatedAt: "2026-06-08T08:00:00Z", windowDays: 7, aiMode: "mock", internalOnly: true, readonly: true, providerCallMade: false, externalActionTaken: false, liveAutonomousLocked: true, phase: "16N" },
  executiveSummary: ["3 open internal action(s)."],
  attentionItems: { total: 0, blockedCount: 0, overdueCount: 0, dueSoonCount: 0, unassignedHighPriority: 0, pendingSuggestions: 0, pendingInternalActions: 0, slaRiskCount: 0, blocked: [], overdue: [], unassignedHigh: [], items: [] },
  departmentSummary: [], memberSummary: [], safeRecommendations: [],
  slaSummary: { overdue: 0, dueSoon: 0, onTrack: 0, noDueDate: 0, overdueByDepartment: {}, dueSoonByDepartment: {}, highestRiskDepartment: "" },
  blockedLiveActions: [{ channel: "whatsapp", label: "WhatsApp / Meta Cloud", locked: true, reason: "no send" }],
  safetySnapshot: { aiPaused: true, sandboxOn: false, syncLive: true, aiMode: "mock", liveAutonomousExecutionLocked: true, providerLiveActionsLocked: true, humanApprovalRequired: true, providerCallMade: false, externalActionTaken: false, phase15ShellFrozen: true, phase15ShellFrozenCommit: "eefd8b3" },
  generatedAt: "2026-06-08T08:00:00Z", windowDays: 7, readonly: true, internalOnly: true,
  providerCallMade: false, providerActionTaken: false, externalActionAllowed: false, externalActionTaken: false, liveAutonomousLocked: true, phase: "16N",
};

const SNAP = {
  id: 1, title: "Director AI briefing — 2026-06-08 08:00 (last 7d)", windowDays: 7,
  status: "unreviewed" as const, aiMode: "mock", readonly: true, internalOnly: true,
  providerCallMade: false, externalActionTaken: false, liveAutonomousLocked: true,
  directorNote: "", createdBy: "director", acknowledgedBy: null, acknowledgedAt: null,
  createdAt: "2026-06-08T08:00:00Z", updatedAt: "2026-06-08T08:00:00Z",
  attentionItems: BRIEFING.attentionItems,
};

const SNAP_DETAIL = {
  ...SNAP,
  executiveSummary: ["3 open internal action(s)."],
  recommendations: [{ recommendationType: "review_blocked_actions", priority: "high" as const, reason: "1 blocked.", linkedMetric: "blockers.blockedCount", permittedAction: "review_blocker" }],
  blockedLiveActions: BRIEFING.blockedLiveActions,
  safetySnapshot: BRIEFING.safetySnapshot,
  events: [
    { id: 1, snapshotId: 1, eventType: "created", note: "Saved.", actor: "director", metadata: {}, createdAt: "2026-06-08T08:00:00Z" },
  ],
};

const SUMMARY = {
  total: 1, unreviewed: 1, acknowledged: 0, needsFollowUp: 0, archived: 0,
  lastSnapshotAt: "2026-06-08T08:00:00Z", byStatus: { unreviewed: 1 },
  readonly: true, internalOnly: true, providerCallMade: false, externalActionTaken: false,
  liveAutonomousLocked: true, phase: "16O",
};

const renderPage = () =>
  render(<MemoryRouter><AiCopilot /></MemoryRouter>);

beforeEach(() => {
  vi.clearAllMocks();
  (api.getAiCopilotStatus as any).mockResolvedValue(STATUS);
  (api.getAiCopilotSuggestions as any).mockResolvedValue({ items: [], total: 0 });
  (api.getAiActionQueue as any).mockResolvedValue({ items: [], total: 0 });
  (api.getAiWorkboard as any).mockResolvedValue({ items: [], total: 0, departments: [], workStatuses: [], myPermissions: MY_PERMISSIONS });
  (api.getAiWorkboardSummary as any).mockResolvedValue({ total: 0, unassigned: 0, assigned: 0, inProgress: 0, blocked: 0, completedInternal: 0, overdue: 0, directorAttention: 0, byWorkStatus: {}, byDepartment: {}, providerActionsLocked: true, liveAutonomousExecutionLocked: true, noProviderActionTaken: true, phase: "16K" });
  (api.getAiWorkboardDirectorAttention as any).mockResolvedValue({ items: [], total: 0 });
  (api.getAiMyWork as any).mockResolvedValue({ items: [], total: 0, myPermissions: MY_PERMISSIONS });
  (api.getAiMyWorkSummary as any).mockResolvedValue({ total: 0, assigned: 0, inProgress: 0, blocked: 0, completedInternal: 0, dueSoon: 0, overdue: 0, byWorkStatus: {}, providerActionsLocked: true, noProviderActionTaken: true, phase: "16L" });
  (api.getAiWorkboardAnalytics as any).mockResolvedValue(null);
  (api.getAiDirectorBriefing as any).mockResolvedValue(BRIEFING);
  (api.getAiDirectorBriefingSnapshots as any).mockResolvedValue({ items: [SNAP], total: 1, statuses: ["unreviewed", "acknowledged", "needs_follow_up", "archived"] });
  (api.getAiDirectorBriefingSnapshotSummary as any).mockResolvedValue(SUMMARY);
  (api.getAiDirectorBriefingSnapshot as any).mockResolvedValue(SNAP_DETAIL);
  (api.createAiDirectorBriefingSnapshot as any).mockResolvedValue(SNAP_DETAIL);
  (api.acknowledgeAiDirectorBriefingSnapshot as any).mockResolvedValue({ ...SNAP, status: "acknowledged" });
  (api.markAiDirectorBriefingSnapshotNeedsFollowUp as any).mockResolvedValue({ ...SNAP, status: "needs_follow_up" });
  (api.archiveAiDirectorBriefingSnapshot as any).mockResolvedValue({ ...SNAP, status: "archived" });
  (api.addAiDirectorBriefingSnapshotNote as any).mockResolvedValue({ ...SNAP, directorNote: "note" });
});

describe("Phase 16O — Director Briefing History", () => {
  it("renders the Director Briefing History section", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-briefing-history-section")).toBeInTheDocument();
  });

  it("renders the internal-only safety copy", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-briefing-history-safety-copy")).toHaveTextContent(
      /briefing snapshots are internal records only/i,
    );
  });

  it("renders snapshot summary cards", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-briefing-history-summary")).toBeInTheDocument();
  });

  it("renders the snapshot list", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-briefing-history-list")).toBeInTheDocument();
    expect(screen.getByTestId("ai-briefing-snapshot-1")).toBeInTheDocument();
  });

  it("Save current briefing snapshot calls the internal POST only", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("ai-briefing-snapshot-save"));
    await waitFor(() => expect(api.createAiDirectorBriefingSnapshot).toHaveBeenCalled());
    expect(api.createImportOrder).not.toHaveBeenCalled();
    expect(api.transitionPilotTask).not.toHaveBeenCalled();
  });

  it("View details fetches + renders snapshot detail", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("ai-briefing-snapshot-view-1"));
    await waitFor(() => expect(api.getAiDirectorBriefingSnapshot).toHaveBeenCalledWith(1));
    expect(await screen.findByTestId("ai-briefing-snapshot-detail-1")).toBeInTheDocument();
    expect(screen.getByTestId("ai-briefing-snapshot-events-1")).toBeInTheDocument();
  });

  it("Acknowledge calls the internal API only", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("ai-briefing-snapshot-acknowledge-1"));
    await waitFor(() => expect(api.acknowledgeAiDirectorBriefingSnapshot).toHaveBeenCalledWith(1));
    expect(api.createImportOrder).not.toHaveBeenCalled();
  });

  it("Mark needs follow-up calls the internal API only", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("ai-briefing-snapshot-follow-up-1"));
    await waitFor(() => expect(api.markAiDirectorBriefingSnapshotNeedsFollowUp).toHaveBeenCalledWith(1));
  });

  it("Archive calls the internal API only", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("ai-briefing-snapshot-archive-1"));
    await waitFor(() => expect(api.archiveAiDirectorBriefingSnapshot).toHaveBeenCalledWith(1));
  });

  it("Add note calls the internal API only", async () => {
    renderPage();
    await screen.findByTestId("ai-briefing-snapshot-1");
    fireEvent.change(screen.getByTestId("ai-briefing-snapshot-note-input-1"), { target: { value: "obs" } });
    fireEvent.click(screen.getByTestId("ai-briefing-snapshot-note-1"));
    await waitFor(() => expect(api.addAiDirectorBriefingSnapshotNote).toHaveBeenCalledWith(1, { note: "obs" }));
  });

  it("renders a safe empty state when there are no snapshots", async () => {
    (api.getAiDirectorBriefingSnapshots as any).mockResolvedValue({ items: [], total: 0, statuses: [] });
    renderPage();
    expect(await screen.findByTestId("ai-briefing-history-empty")).toBeInTheDocument();
  });

  it("renders the error state when status fails", async () => {
    (api.getAiCopilotStatus as any).mockRejectedValue(new Error("boom"));
    renderPage();
    expect(await screen.findByTestId("ai-copilot-error")).toBeInTheDocument();
  });

  it("still renders the Phase 16N Director AI Briefing section", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-director-briefing-section")).toBeInTheDocument();
  });

  it("has no live-action / provider / send button in the history section", async () => {
    renderPage();
    const section = await screen.findByTestId("ai-briefing-history-section");
    expect(
      within(section).queryByRole("button", {
        name: /send whatsapp|create payment link|book shipment|call customer|run live ai|resume ai|auto execute|send briefing|capture|refund/i,
      }),
    ).not.toBeInTheDocument();
    expect(section.textContent || "").not.toMatch(
      /send whatsapp|create payment link|book shipment|call customer|run live ai|resume ai|auto execute|send briefing/i,
    );
  });
});
