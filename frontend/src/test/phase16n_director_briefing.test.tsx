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
      // Phase 16N.
      getAiDirectorBriefing: vi.fn(),
      getAiDirectorBriefingSnapshots: vi.fn(),
      getAiDirectorBriefingSnapshotSummary: vi.fn(),
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

const ANALYTICS = {
  summary: {
    total: 4, openActions: 3, unassigned: 1, assigned: 1, inProgress: 0,
    blocked: 1, completedInternal: 1, overdue: 1, dueSoon: 0, noDueDate: 3,
    directorAttention: 2, closed: 1, avgCompletionHours: 8.0,
  },
  departments: [
    { department: "calling", label: "Calling", total: 2, open: 2, assigned: 1, inProgress: 0, blocked: 1, completedInternal: 0, overdue: 1, dueSoon: 0, noDueDate: 1, completionRate: 0, avgCompletionHours: null, oldestOpenAgeHours: 30 },
  ],
  members: [
    { userId: 5, username: "ops", departments: ["calling"], assignedOpen: 1, inProgress: 0, blocked: 1, overdue: 1, completedInternalRecent: 0, avgCompletionHours: null },
  ],
  sla: { overdue: 1, dueSoon: 0, onTrack: 1, noDueDate: 2, overdueByDepartment: { calling: 1 }, dueSoonByDepartment: {}, highestRiskDepartment: "calling" },
  blockers: { blockedCount: 1, topBlockerReasons: [{ reason: "waiting", count: 1 }], blockedByDepartment: { calling: 1 }, oldestBlockedAgeHours: 30 },
  trend: { windowDays: 14, hasData: false, reason: "insufficient_event_data", days: [] },
  generatedAt: "2026-06-08T08:00:00Z", windowDays: 14, readonly: true, internalOnly: true,
  providerActionAttempted: false, providerActionTaken: false, externalActionAllowed: false, externalActionTaken: false, phase: "16M",
};

const BRIEFING = {
  briefingStatus: {
    generatedAt: "2026-06-08T08:00:00Z", windowDays: 7, aiMode: "mock",
    internalOnly: true, readonly: true, providerCallMade: false,
    externalActionTaken: false, liveAutonomousLocked: true, phase: "16N",
  },
  executiveSummary: [
    "3 open internal action(s): 1 overdue, 1 blocked, 0 due soon.",
    "1 AI suggestion(s) await human review; 0 internal action(s) pending.",
    "All live/customer-facing automation remains LOCKED (AI Paused, Sandbox OFF, Live Autonomous Locked); this briefing is internal-only and read-only.",
  ],
  attentionItems: {
    total: 2, blockedCount: 1, overdueCount: 1, dueSoonCount: 0,
    unassignedHighPriority: 1, pendingSuggestions: 1, pendingInternalActions: 0, slaRiskCount: 1,
    blocked: [{ id: 4, title: "QA review", department: "calling", workStatus: "blocked", priority: "high", slaStatus: "overdue", assigneeUser: "ops", reason: "blocked" }],
    overdue: [{ id: 4, title: "QA review", department: "calling", workStatus: "blocked", priority: "high", slaStatus: "overdue", assigneeUser: "ops", reason: "overdue" }],
    unassignedHigh: [{ id: 7, title: "Urgent calling", department: "unassigned", workStatus: "unassigned", priority: "urgent", slaStatus: "no_due_date", assigneeUser: null, reason: "unassigned_high_priority" }],
    items: [
      { id: 4, title: "QA review", department: "calling", workStatus: "blocked", priority: "high", slaStatus: "overdue", assigneeUser: "ops", reason: "blocked" },
      { id: 7, title: "Urgent calling", department: "unassigned", workStatus: "unassigned", priority: "urgent", slaStatus: "no_due_date", assigneeUser: null, reason: "unassigned_high_priority" },
    ],
  },
  departmentSummary: [
    { department: "calling", label: "Calling", open: 2, assigned: 1, inProgress: 0, blocked: 1, overdue: 1, dueSoon: 0, completedInternal: 0, recommendedFocus: "Clear 1 overdue item(s)." },
  ],
  memberSummary: ANALYTICS.members,
  safeRecommendations: [
    { recommendationType: "review_blocked_actions", priority: "high", reason: "1 internal action(s) are blocked and stopping work (top reason: waiting).", linkedMetric: "blockers.blockedCount", permittedAction: "review_blocker" },
    { recommendationType: "assign_unassigned_high_priority", priority: "high", reason: "1 high/urgent internal action(s) are unassigned.", linkedMetric: "attention.unassignedHighPriority", permittedAction: "assign_internal" },
  ],
  slaSummary: ANALYTICS.sla,
  blockedLiveActions: [
    { channel: "whatsapp", label: "WhatsApp / Meta Cloud", locked: true, reason: "no send" },
    { channel: "payment", label: "Razorpay / PayU payment", locked: true, reason: "no payment" },
    { channel: "courier", label: "Delhivery courier / AWB", locked: true, reason: "no awb" },
    { channel: "vapi", label: "Vapi / voice call", locked: true, reason: "no call" },
    { channel: "live_ai", label: "Live AI / LLM provider", locked: true, reason: "no live ai" },
  ],
  safetySnapshot: {
    aiPaused: true, sandboxOn: false, syncLive: true, aiMode: "mock",
    liveAutonomousExecutionLocked: true, providerLiveActionsLocked: true,
    humanApprovalRequired: true, providerCallMade: false, externalActionTaken: false,
    phase15ShellFrozen: true, phase15ShellFrozenCommit: "eefd8b3",
  },
  generatedAt: "2026-06-08T08:00:00Z", windowDays: 7, readonly: true, internalOnly: true,
  providerCallMade: false, providerActionTaken: false, externalActionAllowed: false,
  externalActionTaken: false, liveAutonomousLocked: true, phase: "16N",
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
  (api.getAiWorkboard as any).mockResolvedValue({ items: [], total: 0, departments: [], workStatuses: [], myPermissions: MY_PERMISSIONS });
  (api.getAiWorkboardSummary as any).mockResolvedValue({
    total: 0, unassigned: 0, assigned: 0, inProgress: 0, blocked: 0, completedInternal: 0,
    overdue: 0, directorAttention: 0, byWorkStatus: {}, byDepartment: {},
    providerActionsLocked: true, liveAutonomousExecutionLocked: true, noProviderActionTaken: true, phase: "16K",
  });
  (api.getAiWorkboardDirectorAttention as any).mockResolvedValue({ items: [], total: 0 });
  (api.getAiMyWork as any).mockResolvedValue({ items: [], total: 0, myPermissions: MY_PERMISSIONS });
  (api.getAiMyWorkSummary as any).mockResolvedValue({
    total: 0, assigned: 0, inProgress: 0, blocked: 0, completedInternal: 0,
    dueSoon: 0, overdue: 0, byWorkStatus: {}, providerActionsLocked: true, noProviderActionTaken: true, phase: "16L",
  });
  (api.getAiWorkboardAnalytics as any).mockResolvedValue(ANALYTICS);
  (api.getAiDirectorBriefing as any).mockResolvedValue(BRIEFING);
  (api.getAiDirectorBriefingSnapshots as any).mockResolvedValue({ items: [], total: 0, statuses: [] });
  (api.getAiDirectorBriefingSnapshotSummary as any).mockResolvedValue(null);
});

describe("Phase 16N — Director AI Daily Briefing", () => {
  it("renders the Director AI Briefing section", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-director-briefing-section")).toBeInTheDocument();
  });

  it("renders the read-only / internal-only safety copy", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-briefing-safety-copy")).toHaveTextContent(
      /read-only internal briefing only — this ai briefing is generated deterministically/i,
    );
  });

  it("renders briefing summary cards", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-briefing-cards")).toBeInTheDocument();
  });

  it("renders the executive summary bullets", async () => {
    renderPage();
    const summary = await screen.findByTestId("ai-briefing-summary");
    expect(summary).toHaveTextContent(/3 open internal action/i);
  });

  it("renders attention items", async () => {
    renderPage();
    const att = await screen.findByTestId("ai-briefing-attention");
    expect(att).toHaveTextContent("QA review");
    expect(att).toHaveTextContent("Urgent calling");
  });

  it("renders safe recommendations with priority + permitted action", async () => {
    renderPage();
    const recs = await screen.findByTestId("ai-briefing-recommendations");
    expect(within(recs).getByTestId("ai-briefing-rec-review_blocked_actions")).toHaveTextContent(/review blocker/i);
    expect(within(recs).getByTestId("ai-briefing-rec-assign_unassigned_high_priority")).toHaveTextContent(/assign internal/i);
  });

  it("renders the blocked live actions list", async () => {
    renderPage();
    const blocked = await screen.findByTestId("ai-briefing-blocked-live");
    for (const ch of ["whatsapp", "payment", "courier", "vapi", "live_ai"]) {
      expect(within(blocked).getByTestId(`ai-briefing-locked-${ch}`)).toHaveTextContent(/locked/i);
    }
  });

  it("renders the department focus table", async () => {
    renderPage();
    const dept = await screen.findByTestId("ai-briefing-departments");
    expect(dept).toHaveTextContent("Calling");
    expect(dept).toHaveTextContent(/clear 1 overdue/i);
  });

  it("refresh briefing calls the internal GET API only", async () => {
    renderPage();
    const btn = await screen.findByTestId("ai-briefing-refresh");
    (api.getAiDirectorBriefing as any).mockClear();
    fireEvent.click(btn);
    await waitFor(() => expect(api.getAiDirectorBriefing).toHaveBeenCalled());
    expect(api.createImportOrder).not.toHaveBeenCalled();
    expect(api.transitionPilotTask).not.toHaveBeenCalled();
    expect(api.applyAiAction).not.toHaveBeenCalled();
  });

  it("renders a safe empty state when briefing is unavailable", async () => {
    (api.getAiDirectorBriefing as any).mockResolvedValue(null);
    renderPage();
    expect(await screen.findByTestId("ai-briefing-empty")).toHaveTextContent(/no urgent briefing items yet/i);
  });

  it("renders the error state when status fails", async () => {
    (api.getAiCopilotStatus as any).mockRejectedValue(new Error("boom"));
    renderPage();
    expect(await screen.findByTestId("ai-copilot-error")).toBeInTheDocument();
  });

  it("still renders the Phase 16M Workboard Analytics section", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-workboard-analytics-section")).toBeInTheDocument();
  });

  it("has no live-action / provider / mutation button in the briefing section", async () => {
    renderPage();
    const section = await screen.findByTestId("ai-director-briefing-section");
    expect(
      within(section).queryByRole("button", {
        name: /send whatsapp|create payment link|book shipment|call customer|run live ai|run ai live|auto execute|resume ai|capture|refund|dispatch/i,
      }),
    ).not.toBeInTheDocument();
    expect(section.textContent || "").not.toMatch(
      /send whatsapp|create live payment|book shipment|call customer|run live ai|auto execute|resume ai/i,
    );
  });
});
