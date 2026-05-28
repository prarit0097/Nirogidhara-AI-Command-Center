import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Preserve real isApiError / ApiError; replace only the `api` object.
vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return {
    ...actual,
    api: {
      getDirectorBriefingOverview: vi.fn(),
      createDirectorBriefingReview: vi.fn(),
      // Representative provider/business methods — must never be called from
      // this page. Spied so the test can assert no side-effect path fired.
      getTeamRoles: vi.fn(),
      assignTeamRole: vi.fn(),
    },
  };
});

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import DirectorBriefing from "@/pages/DirectorBriefing";
import { api } from "@/services/api";

const MISSING_OVERVIEW = {
  briefing: {
    status: "missing" as const,
    source: "unavailable" as const,
    snapshotId: null,
    generatedAt: null,
    updatedAt: null,
    ageMinutes: null,
    healthScore: null,
    healthTier: null,
    briefingText: "",
    alerts: [],
    top3Priorities: [],
  },
  readiness: {
    baseline: "Phase 16B (production verified)",
    safetyShellFrozen: true,
    liveAutomationApproved: false,
    currentPhase: "Phase 16C",
  },
  latestReview: null,
  reviewCount: 0,
  generatedByProvider: false as const,
};

const FRESH_OVERVIEW = {
  ...MISSING_OVERVIEW,
  briefing: {
    status: "fresh" as const,
    source: "system_snapshot" as const,
    snapshotId: 12,
    generatedAt: "2026-05-28T06:00:00Z",
    updatedAt: "2026-05-28T06:00:00Z",
    ageMinutes: 30,
    healthScore: 74,
    healthTier: "good",
    briefingText: "Business looks steady.",
    alerts: [],
    top3Priorities: ["p1"],
  },
};

const renderPage = () =>
  render(
    <MemoryRouter>
      <DirectorBriefing />
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.clearAllMocks();
  (api.getDirectorBriefingOverview as any).mockResolvedValue(MISSING_OVERVIEW);
  (api.createDirectorBriefingReview as any).mockResolvedValue({
    id: 1,
    reviewerUsername: "you",
    note: "ok",
    decisionStatus: "reviewed",
    snapshotRef: null,
    createdAt: "2026-05-28T07:00:00Z",
    updatedAt: "2026-05-28T07:00:00Z",
  });
});

describe("Phase 16C — Director Daily Briefing page", () => {
  it("renders the empty state + safety copy when no snapshot exists", async () => {
    renderPage();
    expect(await screen.findByTestId("director-briefing-page")).toBeInTheDocument();
    expect(screen.getByTestId("briefing-empty-state")).toBeInTheDocument();
    expect(screen.getByTestId("briefing-safety-copy")).toHaveTextContent(
      /no whatsapp \/ payment \/ courier \/ calling \/ ai provider/i,
    );
  });

  it("renders latest status when the API returns a fresh snapshot", async () => {
    (api.getDirectorBriefingOverview as any).mockResolvedValue(FRESH_OVERVIEW);
    renderPage();
    const pill = await screen.findByTestId("briefing-status-pill");
    expect(pill).toHaveAttribute("data-briefing-status", "fresh");
    expect(screen.getByText("74/100")).toBeInTheDocument();
    expect(screen.getByText("Business looks steady.")).toBeInTheDocument();
  });

  it("records a review via the internal API only (no provider call)", async () => {
    renderPage();
    await screen.findByTestId("briefing-review-form");

    fireEvent.change(screen.getByTestId("briefing-note-input"), {
      target: { value: "Pilot calling team first." },
    });
    fireEvent.click(screen.getByTestId("briefing-save-button"));

    await waitFor(() =>
      expect(api.createDirectorBriefingReview).toHaveBeenCalledTimes(1),
    );
    expect(api.createDirectorBriefingReview).toHaveBeenCalledWith({
      note: "Pilot calling team first.",
      decisionStatus: "reviewed",
      snapshotRef: null,
    });
    // No team-role / provider path fired from the briefing page.
    expect(api.assignTeamRole).not.toHaveBeenCalled();
  });
});
