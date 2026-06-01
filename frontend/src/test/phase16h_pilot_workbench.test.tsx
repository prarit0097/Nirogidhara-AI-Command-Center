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
      getPilotPlans: vi.fn(),
      getPilotExecutionSummary: vi.fn(),
      getPilotPlanTasks: vi.fn(),
      generatePilotTasks: vi.fn(),
      transitionPilotTask: vi.fn(),
      assignPilotTask: vi.fn(),
      // Representative provider/business methods — must never be called here.
      createImportOrder: vi.fn(),
      transitionPilotPlan: vi.fn(),
    },
  };
});

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

import PilotWorkbench from "@/pages/PilotWorkbench";
import { api } from "@/services/api";

const here = dirname(fileURLToPath(import.meta.url));

const SAFETY = {
  aiPaused: true,
  sandboxOn: false,
  syncLive: true,
  providerLiveActionsLocked: true,
  phase15ShellFrozen: true,
  phase: "16H",
};

const SUMMARY = {
  planId: null,
  byTeam: [
    { teamRole: "calling_agent" as const, teamLabel: "Calling", total: 3, todo: 1, inProgress: 1, blocked: 0, done: 1, skipped: 0, cancelled: 0, progressPct: 33 },
  ],
  overall: { total: 3, todo: 1, inProgress: 1, blocked: 0, done: 1, skipped: 0, cancelled: 0, progressPct: 33 },
  teamPerformance: [],
  blockedLiveActions: ["Live Razorpay/PayU — blocked."],
  safety: SAFETY,
  noSideEffect: true,
  generatedByProvider: false as const,
};

const PLANS = {
  items: [
    {
      id: 1, name: "Exec pilot", pilotType: "full_lifecycle" as const, status: "approved_internal" as const,
      ownerUser: "director", ownerTeam: "director_admin", problemCategory: "", productCategory: "",
      objective: "", riskNote: "", allowedListNote: "", maxContacts: 25, plannedStartAt: null, plannedEndAt: null,
      linkedImportCampaignId: null, linkedDatasetId: null, linkedOrderId: null, linkedDryRunId: null,
      safetyAcknowledged: true, providerActionsAllowed: false, providerActionsAttempted: false,
      providerActionsBlocked: true, createdBy: "director", updatedBy: "director",
      createdAt: "2026-06-01T08:00:00Z", updatedAt: "2026-06-01T08:00:00Z",
    },
  ],
  total: 1,
};

const TASK = {
  id: 1, pilotPlanId: 1, teamRole: "calling_agent" as const,
  title: "Call assigned pilot contacts", status: "todo" as const, priority: "normal" as const,
  sequence: 0, assignedTo: null, assignedTeamLabel: "", blockedReason: "",
  linkedOrderId: null, linkedImportCampaignId: null, linkedQueueItemId: null,
  providerActionsAllowed: false, providerActionsBlocked: true, createdBy: "director",
  startedAt: null, completedAt: null, createdAt: "2026-06-01T08:30:00Z", updatedAt: "2026-06-01T08:30:00Z",
  description: "", checklist: [], events: [],
};

const TASKS = { items: [TASK], total: 1 };

const renderPage = () =>
  render(
    <MemoryRouter>
      <PilotWorkbench />
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.clearAllMocks();
  (api.getPilotPlans as any).mockResolvedValue(PLANS);
  (api.getPilotExecutionSummary as any).mockResolvedValue(SUMMARY);
  (api.getPilotPlanTasks as any).mockResolvedValue(TASKS);
  (api.generatePilotTasks as any).mockResolvedValue({ items: TASKS.items, created: 1 });
  (api.transitionPilotTask as any).mockResolvedValue({ ...TASK, status: "in_progress" });
});

describe("Phase 16H — Pilot Execution Workbench page", () => {
  it("renders the page + safety banner", async () => {
    renderPage();
    expect(await screen.findByTestId("pilot-workbench-page")).toBeInTheDocument();
    expect(screen.getByTestId("pilot-workbench-safety-copy")).toHaveTextContent(
      /Internal control only — no live provider automation/i,
    );
  });

  it("renders the execution progress dashboard", async () => {
    renderPage();
    expect(await screen.findByTestId("pilot-execution-dashboard")).toBeInTheDocument();
    expect(screen.getByTestId("pilot-team-progress")).toBeInTheDocument();
  });

  it("renders the plan selector", async () => {
    renderPage();
    expect(await screen.findByTestId("pilot-workbench-plan-select")).toBeInTheDocument();
  });

  it("generates role-based task queues via the pilot API only", async () => {
    renderPage();
    await screen.findByTestId("pilot-workbench-plan-select");
    fireEvent.change(screen.getByTestId("pilot-workbench-plan-select"), { target: { value: "1" } });
    await waitFor(() => expect(api.getPilotPlanTasks).toHaveBeenCalledWith(1));
    fireEvent.click(screen.getByTestId("pilot-generate-button"));
    await waitFor(() => expect(api.generatePilotTasks).toHaveBeenCalledWith(1));
    // No provider/business path fired from the workbench.
    expect(api.createImportOrder).not.toHaveBeenCalled();
  });

  it("renders task queues and transitions a task via the internal API only", async () => {
    renderPage();
    await screen.findByTestId("pilot-workbench-plan-select");
    fireEvent.change(screen.getByTestId("pilot-workbench-plan-select"), { target: { value: "1" } });
    expect(await screen.findByTestId("pilot-task-queues")).toBeInTheDocument();
    fireEvent.click(await screen.findByTestId("pilot-task-1-start"));
    await waitFor(() => expect(api.transitionPilotTask).toHaveBeenCalledWith(1, { action: "start", note: "" }));
    expect(api.createImportOrder).not.toHaveBeenCalled();
  });

  it("renders the blocked-live-actions panel", async () => {
    renderPage();
    expect(await screen.findByTestId("pilot-workbench-blocked")).toBeInTheDocument();
  });

  it("renders the error state when summary fails", async () => {
    (api.getPilotExecutionSummary as any).mockRejectedValue(new Error("boom"));
    renderPage();
    expect(await screen.findByTestId("pilot-workbench-error")).toBeInTheDocument();
  });

  it("has no live provider action button", async () => {
    renderPage();
    await screen.findByTestId("pilot-workbench-plan-bar");
    expect(
      screen.queryByRole("button", {
        name: /send whatsapp|create live|book shipment|create payment link|capture|refund|go live|place call/i,
      }),
    ).not.toBeInTheDocument();
  });
});

describe("Phase 16H — wiring", () => {
  it("registers the page route in App.tsx", () => {
    const appSrc = readFileSync(resolve(here, "../App.tsx"), "utf8");
    expect(appSrc).toContain('path="/operations/pilot-workbench"');
  });

  it("adds the sidebar link", () => {
    const sidebarSrc = readFileSync(resolve(here, "../components/layout/Sidebar.tsx"), "utf8");
    expect(sidebarSrc).toContain('to: "/operations/pilot-workbench"');
  });
});
