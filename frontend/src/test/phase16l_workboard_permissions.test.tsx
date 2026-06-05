import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
      // Phase 16L.
      getAiMyWork: vi.fn(),
      getAiMyWorkSummary: vi.fn(),
      getAiMyWorkPermissions: vi.fn(),
      // Phase 16M analytics (the page loads this too).
      getAiWorkboardAnalytics: vi.fn(),
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

const baseAction = {
  id: 0, sourceSuggestionId: 9, actionType: "create_qa_review_task" as const,
  sourceType: "manual" as const, sourceId: "", title: "QA review",
  description: "", assignedTeam: "calling", priority: "high" as const,
  status: "applied_internal" as const, providerActionAttempted: false,
  providerActionTaken: false, externalActionAllowed: false, externalActionTaken: false,
  failureReason: "", approvedBy: "director", appliedBy: "director", createdBy: "director",
  createdAt: "2026-06-04T10:00:00Z", updatedAt: "2026-06-04T10:00:00Z", appliedAt: null,
  resultPayload: {}, safetySnapshot: {}, events: [], workEvents: [],
  department: "calling", assigneeUser: "ops", dueAt: null, slaStatus: "no_due_date" as const,
  blockerReason: "", completedBy: null, completedAt: null, lastActivityAt: null,
};

// A scoped member's view: can work own assigned items, cannot assign/reassign.
const MEMBER_PERMS = {
  canClaim: false, canStart: true, canBlock: true, canUnblock: false,
  canCompleteInternal: true, canAddNote: true, canAssign: false, canReassign: false,
};

const MY_ASSIGNED = { ...baseAction, id: 11, workStatus: "assigned" as const, permissions: MEMBER_PERMS };
const MY_BLOCKED = {
  ...baseAction, id: 12, workStatus: "blocked" as const, blockerReason: "waiting",
  permissions: { ...MEMBER_PERMS, canStart: false, canBlock: false, canUnblock: true },
};

// Workboard item as seen by a non-admin member (assign/reassign hidden).
const WB_UNASSIGNED = {
  ...baseAction, id: 21, assigneeUser: null, workStatus: "unassigned" as const,
  permissions: { canClaim: true, canStart: false, canBlock: false, canUnblock: false,
    canCompleteInternal: false, canAddNote: false, canAssign: false, canReassign: false },
};

const MY_PERMISSIONS = {
  isAdmin: false, canViewWorkboard: true, canAssign: false, canReassign: false,
  canManageMembership: false,
  departments: [{ department: "calling", canClaim: true, canWork: true, canComplete: true }],
  providerActionsLocked: true, liveAutonomousExecutionLocked: true, phase: "16L",
};

const MY_SUMMARY = {
  total: 2, assigned: 1, inProgress: 0, blocked: 1, completedInternal: 0,
  dueSoon: 0, overdue: 1, byWorkStatus: {},
  providerActionsLocked: true, noProviderActionTaken: true, phase: "16L",
};

const renderPage = () =>
  render(
    <MemoryRouter>
      <AiCopilot />
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.clearAllMocks();
  (api.getAiCopilotStatus as any).mockResolvedValue(STATUS);
  (api.getAiCopilotSuggestions as any).mockResolvedValue({ items: [], total: 0 });
  (api.getAiActionQueue as any).mockResolvedValue({ items: [], total: 0 });
  (api.getAiActionSummary as any).mockResolvedValue({
    statusCounts: {}, total: 0, providerActionsLocked: true,
    liveAutonomousExecutionLocked: true, noProviderActionTaken: true, phase: "16J",
  });
  (api.getAiWorkboard as any).mockResolvedValue({
    items: [WB_UNASSIGNED], total: 1, departments: ["calling"], workStatuses: ["unassigned"],
    myPermissions: MY_PERMISSIONS,
  });
  (api.getAiWorkboardSummary as any).mockResolvedValue({
    total: 1, unassigned: 1, assigned: 0, inProgress: 0, blocked: 0, completedInternal: 0,
    overdue: 0, directorAttention: 0, byWorkStatus: {}, byDepartment: {},
    providerActionsLocked: true, liveAutonomousExecutionLocked: true, noProviderActionTaken: true, phase: "16K",
  });
  (api.getAiWorkboardDirectorAttention as any).mockResolvedValue({ items: [], total: 0 });
  (api.getAiMyWork as any).mockResolvedValue({
    items: [MY_ASSIGNED, MY_BLOCKED], total: 2, myPermissions: MY_PERMISSIONS,
  });
  (api.getAiMyWorkSummary as any).mockResolvedValue(MY_SUMMARY);
  (api.getAiWorkboardAnalytics as any).mockResolvedValue(null);
  (api.startAiAction as any).mockResolvedValue({ ...MY_ASSIGNED, workStatus: "in_progress" });
  (api.blockAiAction as any).mockResolvedValue({ ...MY_ASSIGNED, workStatus: "blocked" });
  (api.unblockAiAction as any).mockResolvedValue({ ...MY_BLOCKED, workStatus: "in_progress" });
  (api.completeInternalAiAction as any).mockResolvedValue({ ...MY_ASSIGNED, workStatus: "completed_internal" });
  (api.claimAiAction as any).mockResolvedValue({ ...WB_UNASSIGNED, workStatus: "assigned" });
  (api.addAiActionNote as any).mockResolvedValue({ ...MY_ASSIGNED });
});

describe("Phase 16L — My Work Queue + scoped permissions", () => {
  it("renders the My Work section + safety copy", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-my-work-section")).toBeInTheDocument();
    expect(screen.getByTestId("ai-my-work-safety-copy")).toHaveTextContent(
      /only update internal workboard records they are assigned to or allowed to claim/i,
    );
  });

  it("renders My Work summary cards", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-my-work-summary")).toBeInTheDocument();
  });

  it("renders My Work items", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-my-work-list")).toBeInTheDocument();
    expect(screen.getByTestId("ai-my-work-item-11")).toBeInTheDocument();
    expect(screen.getByTestId("ai-my-work-item-12")).toBeInTheDocument();
  });

  it("renders My Work empty state when no items", async () => {
    (api.getAiMyWork as any).mockResolvedValue({ items: [], total: 0, myPermissions: MY_PERMISSIONS });
    renderPage();
    expect(await screen.findByTestId("ai-my-work-empty")).toBeInTheDocument();
  });

  it("shows only permitted buttons on My Work items", async () => {
    renderPage();
    await screen.findByTestId("ai-my-work-item-11");
    // assigned item: start + block + complete + note (per MEMBER_PERMS)
    expect(screen.getByTestId("ai-my-work-start-11")).toBeInTheDocument();
    expect(screen.getByTestId("ai-my-work-block-11")).toBeInTheDocument();
    expect(screen.getByTestId("ai-my-work-complete-11")).toBeInTheDocument();
    // blocked item: only unblock (no start/block)
    expect(screen.getByTestId("ai-my-work-unblock-12")).toBeInTheDocument();
    expect(screen.queryByTestId("ai-my-work-start-12")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ai-my-work-block-12")).not.toBeInTheDocument();
  });

  it("start calls the internal API only", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("ai-my-work-start-11"));
    await waitFor(() => expect(api.startAiAction).toHaveBeenCalledWith(11));
    expect(api.createImportOrder).not.toHaveBeenCalled();
    expect(api.transitionPilotTask).not.toHaveBeenCalled();
  });

  it("complete calls the internal API only", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("ai-my-work-complete-11"));
    await waitFor(() => expect(api.completeInternalAiAction).toHaveBeenCalledWith(11));
  });

  it("unblock calls the internal API only", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("ai-my-work-unblock-12"));
    await waitFor(() => expect(api.unblockAiAction).toHaveBeenCalledWith(12));
  });

  it("hides assign/reassign in the workboard for non-admin members", async () => {
    renderPage();
    await screen.findByTestId("ai-workboard-item-21");
    // non-admin: claim shown, assign + reassign hidden
    expect(screen.getByTestId("ai-workboard-claim-21")).toBeInTheDocument();
    expect(screen.queryByTestId("ai-workboard-assign-21")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ai-workboard-reassign-21")).not.toBeInTheDocument();
  });

  it("claim calls the internal API only", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("ai-workboard-claim-21"));
    await waitFor(() => expect(api.claimAiAction).toHaveBeenCalledWith(21));
    expect(api.createImportOrder).not.toHaveBeenCalled();
  });

  it("still renders the Phase 16K Department action workboard", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-workboard-section")).toBeInTheDocument();
  });

  it("renders the error state when status fails", async () => {
    (api.getAiCopilotStatus as any).mockRejectedValue(new Error("boom"));
    renderPage();
    expect(await screen.findByTestId("ai-copilot-error")).toBeInTheDocument();
  });

  it("has no live provider action button in My Work", async () => {
    renderPage();
    await screen.findByTestId("ai-my-work-section");
    expect(
      screen.queryByRole("button", {
        name: /send whatsapp|create live payment|book shipment|call customer|run ai live|auto execute|capture|refund/i,
      }),
    ).not.toBeInTheDocument();
  });
});
