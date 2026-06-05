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
      // Phase 16K workboard methods.
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
      // Phase 16L My Work methods (the page loads these too).
      getAiMyWork: vi.fn(),
      getAiMyWorkSummary: vi.fn(),
      getAiMyWorkPermissions: vi.fn(),
      // Phase 16M analytics method (the page loads this too).
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
  description: "", assignedTeam: "", priority: "high" as const,
  status: "applied_internal" as const, providerActionAttempted: false,
  providerActionTaken: false, externalActionAllowed: false, externalActionTaken: false,
  failureReason: "", approvedBy: "director", appliedBy: "director", createdBy: "director",
  createdAt: "2026-06-03T10:00:00Z", updatedAt: "2026-06-03T10:00:00Z", appliedAt: null,
  resultPayload: {}, safetySnapshot: {}, events: [], workEvents: [],
  department: "", assigneeUser: null, dueAt: null, slaStatus: "no_due_date" as const,
  blockerReason: "", completedBy: null, completedAt: null, lastActivityAt: null,
};

const UNASSIGNED = { ...baseAction, id: 1, workStatus: "unassigned" as const };
const ASSIGNED = { ...baseAction, id: 2, workStatus: "assigned" as const, department: "calling", assigneeUser: "director" };
const IN_PROGRESS = { ...baseAction, id: 3, workStatus: "in_progress" as const, department: "qa_compliance", assigneeUser: "director" };
const BLOCKED = { ...baseAction, id: 4, workStatus: "blocked" as const, department: "finance_accounts", blockerReason: "waiting", slaStatus: "overdue" as const };

const SUMMARY = {
  total: 4, unassigned: 1, assigned: 1, inProgress: 1, blocked: 1,
  completedInternal: 0, overdue: 1, directorAttention: 2,
  byWorkStatus: {}, byDepartment: {}, providerActionsLocked: true,
  liveAutonomousExecutionLocked: true, noProviderActionTaken: true, phase: "16K",
};

const ATTENTION = {
  items: [
    { ...BLOCKED, attentionReason: "blocked" },
    { ...UNASSIGNED, attentionReason: "unassigned_high_priority" },
  ],
  total: 2,
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
    items: [UNASSIGNED, ASSIGNED, IN_PROGRESS, BLOCKED], total: 4,
    departments: ["calling", "qa_compliance"], workStatuses: ["unassigned", "assigned"],
  });
  (api.getAiWorkboardSummary as any).mockResolvedValue(SUMMARY);
  (api.getAiWorkboardDirectorAttention as any).mockResolvedValue(ATTENTION);
  (api.getAiMyWork as any).mockResolvedValue({ items: [], total: 0, myPermissions: { isAdmin: true, canViewWorkboard: true, canAssign: true, canReassign: true, canManageMembership: true, departments: [], providerActionsLocked: true, liveAutonomousExecutionLocked: true, phase: "16L" } });
  (api.getAiMyWorkSummary as any).mockResolvedValue({ total: 0, assigned: 0, inProgress: 0, blocked: 0, completedInternal: 0, dueSoon: 0, overdue: 0, byWorkStatus: {}, providerActionsLocked: true, noProviderActionTaken: true, phase: "16L" });
  (api.getAiWorkboardAnalytics as any).mockResolvedValue(null);
  (api.assignAiAction as any).mockResolvedValue({ ...UNASSIGNED, workStatus: "assigned" });
  (api.startAiAction as any).mockResolvedValue({ ...ASSIGNED, workStatus: "in_progress" });
  (api.blockAiAction as any).mockResolvedValue({ ...IN_PROGRESS, workStatus: "blocked" });
  (api.unblockAiAction as any).mockResolvedValue({ ...BLOCKED, workStatus: "in_progress" });
  (api.completeInternalAiAction as any).mockResolvedValue({ ...IN_PROGRESS, workStatus: "completed_internal" });
});

describe("Phase 16K — Department Action Workboard", () => {
  it("renders the workboard section + safety copy", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-workboard-section")).toBeInTheDocument();
    expect(screen.getByTestId("ai-workboard-safety-copy")).toHaveTextContent(
      /never sends WhatsApp, creates payment links, books shipments, calls customers, invokes Vapi, or calls a live AI provider/i,
    );
  });

  it("renders summary cards", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-workboard-summary")).toBeInTheDocument();
  });

  it("renders filters", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-workboard-filters")).toBeInTheDocument();
    expect(screen.getByTestId("ai-workboard-filter-department")).toBeInTheDocument();
    expect(screen.getByTestId("ai-workboard-filter-sla")).toBeInTheDocument();
  });

  it("renders the workboard list with items", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-workboard-list")).toBeInTheDocument();
    expect(screen.getByTestId("ai-workboard-item-1")).toBeInTheDocument();
    expect(screen.getByTestId("ai-workboard-item-4")).toBeInTheDocument();
  });

  it("renders the director attention section with blocked/overdue items", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-workboard-attention")).toBeInTheDocument();
    expect(screen.getByTestId("ai-workboard-attention-4")).toBeInTheDocument();
  });

  it("renders empty state when no items", async () => {
    (api.getAiWorkboard as any).mockResolvedValue({ items: [], total: 0, departments: [], workStatuses: [] });
    renderPage();
    expect(await screen.findByTestId("ai-workboard-empty")).toBeInTheDocument();
  });

  it("assign calls the internal API only", async () => {
    renderPage();
    await screen.findByTestId("ai-workboard-item-1");
    fireEvent.change(screen.getByTestId("ai-workboard-dept-1"), { target: { value: "calling" } });
    fireEvent.click(screen.getByTestId("ai-workboard-assign-1"));
    await waitFor(() =>
      expect(api.assignAiAction).toHaveBeenCalledWith(1, expect.objectContaining({ department: "calling" })),
    );
    expect(api.createImportOrder).not.toHaveBeenCalled();
    expect(api.transitionPilotTask).not.toHaveBeenCalled();
  });

  it("start calls the internal API only", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("ai-workboard-start-2"));
    await waitFor(() => expect(api.startAiAction).toHaveBeenCalledWith(2));
    expect(api.createImportOrder).not.toHaveBeenCalled();
  });

  it("block calls the internal API only with a reason", async () => {
    renderPage();
    await screen.findByTestId("ai-workboard-item-3");
    fireEvent.change(screen.getByTestId("ai-workboard-reason-3"), { target: { value: "stuck" } });
    fireEvent.click(screen.getByTestId("ai-workboard-block-3"));
    await waitFor(() =>
      expect(api.blockAiAction).toHaveBeenCalledWith(3, expect.objectContaining({ reason: "stuck" })),
    );
  });

  it("unblock + complete call the internal API only", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("ai-workboard-unblock-4"));
    await waitFor(() => expect(api.unblockAiAction).toHaveBeenCalledWith(4));
    fireEvent.click(screen.getByTestId("ai-workboard-complete-3"));
    await waitFor(() => expect(api.completeInternalAiAction).toHaveBeenCalledWith(3));
  });

  it("has no live provider action button in the workboard", async () => {
    renderPage();
    await screen.findByTestId("ai-workboard-section");
    expect(
      screen.queryByRole("button", {
        name: /send whatsapp|create live payment|book shipment|call customer|run ai live|auto execute|capture|refund/i,
      }),
    ).not.toBeInTheDocument();
  });
});
