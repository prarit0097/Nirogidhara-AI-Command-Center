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

const APPROVED_SUGGESTION = {
  id: 7, suggestionType: "director_briefing" as const, sourceType: "manual" as const,
  sourceId: "", title: "Approved suggestion", summary: "s", recommendation: "r",
  riskFlags: [], confidenceScore: 0.6, aiMode: "mock" as const,
  status: "approved" as const, reviewerNote: "", providerCallMade: false,
  externalActionAllowed: false, externalActionTaken: false, createdBy: "director",
  reviewedBy: "director", createdAt: "2026-06-02T10:00:00Z", updatedAt: "2026-06-02T10:00:00Z",
  detail: {}, events: [],
};

const ACTION = {
  id: 1, sourceSuggestionId: 7, actionType: "create_qa_review_task" as const,
  sourceType: "manual" as const, sourceId: "", title: "QA review",
  description: "", assignedTeam: "qa_compliance", priority: "high" as const,
  status: "pending_internal_action" as const, providerActionAttempted: false,
  providerActionTaken: false, externalActionAllowed: false, externalActionTaken: false,
  failureReason: "", approvedBy: "director", appliedBy: null, createdBy: "director",
  createdAt: "2026-06-02T10:00:00Z", updatedAt: "2026-06-02T10:00:00Z", appliedAt: null,
  resultPayload: {}, safetySnapshot: {}, events: [],
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
  (api.getAiCopilotSuggestions as any).mockResolvedValue({ items: [APPROVED_SUGGESTION], total: 1 });
  (api.getAiActionQueue as any).mockResolvedValue({ items: [ACTION], total: 1 });
  (api.getAiActionSummary as any).mockResolvedValue({
    statusCounts: {}, total: 1, providerActionsLocked: true,
    liveAutonomousExecutionLocked: true, noProviderActionTaken: true, phase: "16J",
  });
  (api.createAiActionFromSuggestion as any).mockResolvedValue(ACTION);
  (api.applyAiAction as any).mockResolvedValue({ ...ACTION, status: "applied_internal" });
  (api.rejectAiAction as any).mockResolvedValue({ ...ACTION, status: "rejected" });
  (api.cancelAiAction as any).mockResolvedValue({ ...ACTION, status: "cancelled" });
});

describe("Phase 16J — AI action queue section", () => {
  it("renders the action queue section + safety copy", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-action-queue-section")).toBeInTheDocument();
    expect(screen.getByTestId("ai-action-safety-copy")).toHaveTextContent(
      /does not send WhatsApp, create payment links, book shipments, call customers, or invoke live AI providers/i,
    );
  });

  it("lists approved suggestions ready for internal action", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-action-approved-list")).toBeInTheDocument();
    expect(screen.getByTestId("ai-action-create-7")).toBeInTheDocument();
  });

  it("creates an internal action via the ai-copilot API only", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("ai-action-create-7"));
    await waitFor(() =>
      expect(api.createAiActionFromSuggestion).toHaveBeenCalledWith(
        expect.objectContaining({ suggestionId: 7, actionType: "create_qa_review_task" }),
      ),
    );
    expect(api.createImportOrder).not.toHaveBeenCalled();
    expect(api.transitionPilotTask).not.toHaveBeenCalled();
  });

  it("renders the internal action queue", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-action-1")).toBeInTheDocument();
  });

  it("applies an internal action via the internal API only", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("ai-action-apply-1"));
    await waitFor(() => expect(api.applyAiAction).toHaveBeenCalledWith(1));
    expect(api.createImportOrder).not.toHaveBeenCalled();
  });

  it("rejects and cancels via the internal API only", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("ai-action-reject-1"));
    await waitFor(() => expect(api.rejectAiAction).toHaveBeenCalledWith(1));
    fireEvent.click(screen.getByTestId("ai-action-cancel-1"));
    await waitFor(() => expect(api.cancelAiAction).toHaveBeenCalledWith(1));
  });

  it("has no live provider action button in the action queue", async () => {
    renderPage();
    await screen.findByTestId("ai-action-queue-section");
    expect(
      screen.queryByRole("button", {
        name: /send whatsapp|create live payment|book shipment|call customer|run ai live|capture|refund/i,
      }),
    ).not.toBeInTheDocument();
  });
});
