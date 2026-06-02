import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return {
    ...actual,
    api: {
      getAiCopilotStatus: vi.fn(),
      getAiCopilotSuggestions: vi.fn(),
      generateAiCopilotSuggestion: vi.fn(),
      reviewAiCopilotSuggestion: vi.fn(),
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

const here = dirname(fileURLToPath(import.meta.url));

const STATUS = {
  aiPaused: true,
  sandboxOn: false,
  syncLive: true,
  providerLiveActionsLocked: true,
  liveAutonomousExecutionLocked: true,
  phase15ShellFrozen: true,
  aiMode: "mock" as const,
  liveProviderStatus: "unavailable" as const,
  aiProvider: "disabled",
  humanApprovalRequired: true,
  noProviderCallMade: true,
  phase: "16I",
};

const SUGGESTIONS = {
  items: [
    {
      id: 1,
      suggestionType: "compliance_risk" as const,
      sourceType: "manual" as const,
      sourceId: "",
      title: "Compliance risk review — review_required",
      summary: "2 risk signal(s) detected; human compliance review required.",
      recommendation: "Route to QA/Compliance; do NOT use until approved.",
      riskFlags: ["unapproved_claim_risk", "tone_risk"],
      confidenceScore: 0.75,
      aiMode: "mock" as const,
      status: "pending_review" as const,
      reviewerNote: "",
      providerCallMade: false,
      externalActionAllowed: false,
      externalActionTaken: false,
      createdBy: "director",
      reviewedBy: null,
      createdAt: "2026-06-01T10:00:00Z",
      updatedAt: "2026-06-01T10:00:00Z",
      detail: {},
      events: [],
    },
  ],
  total: 1,
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
  (api.getAiCopilotSuggestions as any).mockResolvedValue(SUGGESTIONS);
  (api.generateAiCopilotSuggestion as any).mockResolvedValue(SUGGESTIONS.items[0]);
  (api.reviewAiCopilotSuggestion as any).mockResolvedValue({
    ...SUGGESTIONS.items[0],
    status: "approved",
  });
});

describe("Phase 16I — AI Copilot Center page", () => {
  it("renders the page + safety banner", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-copilot-page")).toBeInTheDocument();
    expect(screen.getByTestId("ai-copilot-safety-copy")).toHaveTextContent(
      /Internal copilot only — no live autonomous execution/i,
    );
  });

  it("renders the AI safety status chips", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-copilot-status")).toBeInTheDocument();
  });

  it("generates a suggestion via the ai-copilot API only", async () => {
    renderPage();
    await screen.findByTestId("ai-copilot-generate-form");
    fireEvent.click(screen.getByTestId("ai-copilot-generate-button"));
    await waitFor(() => expect(api.generateAiCopilotSuggestion).toHaveBeenCalledTimes(1));
    // No provider/business path fired.
    expect(api.createImportOrder).not.toHaveBeenCalled();
    expect(api.transitionPilotTask).not.toHaveBeenCalled();
  });

  it("renders suggestion cards + risk flags", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-copilot-suggestion-1")).toBeInTheDocument();
    expect(screen.getByTestId("ai-copilot-risk-1")).toHaveTextContent(/unapproved_claim_risk/i);
  });

  it("approve control calls the review API only", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("ai-copilot-approve-1"));
    await waitFor(() =>
      expect(api.reviewAiCopilotSuggestion).toHaveBeenCalledWith(1, { action: "approve" }),
    );
    expect(api.createImportOrder).not.toHaveBeenCalled();
  });

  it("reject control calls the review API only", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("ai-copilot-reject-1"));
    await waitFor(() =>
      expect(api.reviewAiCopilotSuggestion).toHaveBeenCalledWith(1, { action: "reject" }),
    );
  });

  it("renders the error state when status fails", async () => {
    (api.getAiCopilotStatus as any).mockRejectedValue(new Error("boom"));
    renderPage();
    expect(await screen.findByTestId("ai-copilot-error")).toBeInTheDocument();
  });

  it("has no live provider action button", async () => {
    renderPage();
    await screen.findByTestId("ai-copilot-generate-form");
    expect(
      screen.queryByRole("button", {
        name: /send whatsapp|create live|book shipment|create payment link|capture|refund|place call|go live/i,
      }),
    ).not.toBeInTheDocument();
  });
});

describe("Phase 16I — wiring", () => {
  it("registers the page route in App.tsx", () => {
    const appSrc = readFileSync(resolve(here, "../App.tsx"), "utf8");
    expect(appSrc).toContain('path="/operations/ai-copilot"');
  });

  it("adds the sidebar link", () => {
    const sidebarSrc = readFileSync(resolve(here, "../components/layout/Sidebar.tsx"), "utf8");
    expect(sidebarSrc).toContain('to: "/operations/ai-copilot"');
  });
});
