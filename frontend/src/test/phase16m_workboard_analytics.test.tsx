import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
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
      // Phase 16M.
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

const MY_PERMISSIONS = {
  isAdmin: true, canViewWorkboard: true, canAssign: true, canReassign: true,
  canManageMembership: true, departments: [],
  providerActionsLocked: true, liveAutonomousExecutionLocked: true, phase: "16L",
};

const ANALYTICS = {
  summary: {
    total: 6, openActions: 4, unassigned: 1, assigned: 1, inProgress: 1,
    blocked: 1, completedInternal: 1, overdue: 1, dueSoon: 1, noDueDate: 4,
    directorAttention: 2, closed: 1, avgCompletionHours: 12.5,
  },
  departments: [
    {
      department: "calling", label: "Calling", total: 3, open: 2, assigned: 1,
      inProgress: 1, blocked: 1, completedInternal: 0, overdue: 1, dueSoon: 0,
      noDueDate: 2, completionRate: 0.0, avgCompletionHours: null, oldestOpenAgeHours: 48.0,
    },
    {
      department: "finance_accounts", label: "Finance / Accounts", total: 2, open: 1,
      assigned: 0, inProgress: 0, blocked: 0, completedInternal: 1, overdue: 0,
      dueSoon: 1, noDueDate: 1, completionRate: 0.5, avgCompletionHours: 12.5,
      oldestOpenAgeHours: 10.0,
    },
  ],
  members: [
    {
      userId: 5, username: "ops", departments: ["calling"], assignedOpen: 1,
      inProgress: 1, blocked: 1, overdue: 1, completedInternalRecent: 0,
      avgCompletionHours: null,
    },
  ],
  sla: {
    overdue: 1, dueSoon: 1, onTrack: 1, noDueDate: 4,
    overdueByDepartment: { calling: 1 }, dueSoonByDepartment: { finance_accounts: 1 },
    highestRiskDepartment: "calling",
  },
  blockers: {
    blockedCount: 1,
    topBlockerReasons: [{ reason: "Awaiting customer callback", count: 1 }],
    blockedByDepartment: { calling: 1 }, oldestBlockedAgeHours: 30.0,
  },
  trend: {
    windowDays: 14, hasData: true, reason: "",
    days: [
      { date: "2026-06-04", created: 2, assigned: 2, started: 1, blocked: 1, completedInternal: 0 },
      { date: "2026-06-05", created: 1, assigned: 0, started: 0, blocked: 0, completedInternal: 1 },
    ],
  },
  generatedAt: "2026-06-05T12:00:00Z",
  windowDays: 14,
  readonly: true,
  internalOnly: true,
  providerActionAttempted: false,
  providerActionTaken: false,
  externalActionAllowed: false,
  externalActionTaken: false,
  phase: "16M",
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
  (api.getAiWorkboard as any).mockResolvedValue({
    items: [], total: 0, departments: [], workStatuses: [], myPermissions: MY_PERMISSIONS,
  });
  (api.getAiWorkboardSummary as any).mockResolvedValue({
    total: 0, unassigned: 0, assigned: 0, inProgress: 0, blocked: 0, completedInternal: 0,
    overdue: 0, directorAttention: 0, byWorkStatus: {}, byDepartment: {},
    providerActionsLocked: true, liveAutonomousExecutionLocked: true, noProviderActionTaken: true, phase: "16K",
  });
  (api.getAiWorkboardDirectorAttention as any).mockResolvedValue({ items: [], total: 0 });
  (api.getAiMyWork as any).mockResolvedValue({ items: [], total: 0, myPermissions: MY_PERMISSIONS });
  (api.getAiMyWorkSummary as any).mockResolvedValue({
    total: 0, assigned: 0, inProgress: 0, blocked: 0, completedInternal: 0,
    dueSoon: 0, overdue: 0, byWorkStatus: {},
    providerActionsLocked: true, noProviderActionTaken: true, phase: "16L",
  });
  (api.getAiWorkboardAnalytics as any).mockResolvedValue(ANALYTICS);
});

describe("Phase 16M — Workboard Analytics + SLA Throughput Dashboard", () => {
  it("renders the analytics section", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-workboard-analytics-section")).toBeInTheDocument();
  });

  it("renders the safety banner with no-live-action wording", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-analytics-safety-copy")).toHaveTextContent(
      /read-only analytics only — this dashboard never sends whatsapp/i,
    );
  });

  it("renders summary cards", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-analytics-summary")).toBeInTheDocument();
  });

  it("renders the department workload table", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-analytics-dept-table")).toBeInTheDocument();
    expect(screen.getByTestId("ai-analytics-dept-calling")).toBeInTheDocument();
    expect(screen.getByTestId("ai-analytics-dept-finance_accounts")).toBeInTheDocument();
  });

  it("renders the member workload table", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-analytics-member-table")).toBeInTheDocument();
    expect(screen.getByTestId("ai-analytics-member-5")).toHaveTextContent("ops");
  });

  it("renders the SLA / blocker panel", async () => {
    renderPage();
    const panel = await screen.findByTestId("ai-analytics-sla-panel");
    expect(panel).toHaveTextContent(/awaiting customer callback/i);
  });

  it("renders the throughput trend table when data is present", async () => {
    renderPage();
    const trend = await screen.findByTestId("ai-analytics-trend");
    expect(trend).toHaveTextContent("2026-06-04");
  });

  it("renders a safe trend empty state when there is no activity", async () => {
    (api.getAiWorkboardAnalytics as any).mockResolvedValue({
      ...ANALYTICS,
      trend: { windowDays: 14, hasData: false, reason: "insufficient_event_data", days: [] },
    });
    renderPage();
    expect(await screen.findByTestId("ai-analytics-trend-empty")).toBeInTheDocument();
  });

  it("renders the analytics empty state when analytics are unavailable", async () => {
    (api.getAiWorkboardAnalytics as any).mockResolvedValue(null);
    renderPage();
    expect(await screen.findByTestId("ai-analytics-empty")).toBeInTheDocument();
  });

  it("renders the error state when status fails", async () => {
    (api.getAiCopilotStatus as any).mockRejectedValue(new Error("boom"));
    renderPage();
    expect(await screen.findByTestId("ai-copilot-error")).toBeInTheDocument();
  });

  it("has no live-action / provider / mutation button or text in the analytics section", async () => {
    renderPage();
    const section = await screen.findByTestId("ai-workboard-analytics-section");
    // No forbidden buttons.
    expect(
      within(section).queryByRole("button", {
        name: /send whatsapp|create payment link|book shipment|call customer|invoke vapi|run ai live|auto execute|capture|refund|dispatch/i,
      }),
    ).not.toBeInTheDocument();
    // No forbidden phrasing anywhere in the section.
    expect(section.textContent || "").not.toMatch(
      /send whatsapp|create payment link|book shipment|call customer|invoke vapi|run ai live|auto execute/i,
    );
  });

  it("does not call any provider/business api when rendering analytics", async () => {
    renderPage();
    await screen.findByTestId("ai-workboard-analytics-section");
    expect(api.createImportOrder).not.toHaveBeenCalled();
    expect(api.transitionPilotTask).not.toHaveBeenCalled();
    expect(api.applyAiAction).not.toHaveBeenCalled();
    expect(api.assignAiAction).not.toHaveBeenCalled();
  });
});
