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
      getPilotControlSummary: vi.fn(),
      getPilotPlans: vi.fn(),
      getPilotPlan: vi.fn(),
      createPilotPlan: vi.fn(),
      transitionPilotPlan: vi.fn(),
      reviewPilotPlan: vi.fn(),
      // Representative provider/business methods — must never be called here.
      createImportOrder: vi.fn(),
      getPaymentLogisticsReadiness: vi.fn(),
    },
  };
});

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

import PilotControl from "@/pages/PilotControl";
import { api } from "@/services/api";

const here = dirname(fileURLToPath(import.meta.url));

const SAFETY = {
  aiPaused: true,
  sandboxOn: false,
  syncLive: true,
  providerLiveActionsLocked: true,
  phase15ShellFrozen: true,
  phase: "16G",
};

const GATES = [
  { key: "payment_readiness", label: "Payment readiness", status: "blocked" as const, detail: "blocked" },
  { key: "shipment_readiness", label: "Shipment readiness", status: "blocked" as const, detail: "blocked" },
];

const SUMMARY = {
  statusCounts: {
    draft: 1,
    ready_for_review: 0,
    approved_internal: 0,
    running_internal: 0,
    paused: 0,
    completed: 0,
    cancelled: 0,
  },
  totalPlans: 1,
  activePlans: 0,
  safety: SAFETY,
  gates: GATES,
  blockedLiveActions: ["Live Razorpay/PayU — blocked."],
  noSideEffect: true,
  generatedByProvider: false as const,
};

const PLAN = {
  id: 1,
  name: "Joint pain internal pilot",
  pilotType: "full_lifecycle" as const,
  status: "draft" as const,
  ownerUser: "director",
  ownerTeam: "director_admin",
  problemCategory: "Joint pain",
  productCategory: "Joint Care",
  objective: "Rehearse",
  riskNote: "",
  allowedListNote: "",
  maxContacts: 25,
  plannedStartAt: null,
  plannedEndAt: null,
  linkedImportCampaignId: null,
  linkedDatasetId: null,
  linkedOrderId: null,
  linkedDryRunId: null,
  safetyAcknowledged: true,
  providerActionsAllowed: false,
  providerActionsAttempted: false,
  providerActionsBlocked: true,
  createdBy: "director",
  updatedBy: "director",
  createdAt: "2026-06-01T08:00:00Z",
  updatedAt: "2026-06-01T08:00:00Z",
};

const PLAN_DETAIL = {
  ...PLAN,
  events: [
    { id: 1, pilotPlanId: 1, eventType: "created", note: "Pilot plan created (internal).", actor: "director", createdAt: "2026-06-01T08:00:00Z" },
  ],
  reviews: [],
  gateStatus: [
    { key: "team_assigned", label: "Team assigned", status: "pass" as const, detail: "ok" },
    { key: "payment_live_gate_blocked", label: "Payment live gate blocked", status: "pass" as const, detail: "blocked" },
    { key: "whatsapp_blocked", label: "WhatsApp blocked", status: "pass" as const, detail: "blocked" },
  ],
  metrics: {
    campaign: null,
    dataset: null,
    linkedOrderId: null,
    linkedDryRunId: null,
    dryRunStatus: null,
    paymentReadinessStatus: "blocked",
    shipmentReadinessStatus: "ready",
    blockedLiveActions: ["Live Razorpay/PayU — blocked."],
  },
};

const PLANS = { items: [PLAN], total: 1 };

const renderPage = () =>
  render(
    <MemoryRouter>
      <PilotControl />
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.clearAllMocks();
  (api.getPilotControlSummary as any).mockResolvedValue(SUMMARY);
  (api.getPilotPlans as any).mockResolvedValue(PLANS);
  (api.getPilotPlan as any).mockResolvedValue(PLAN_DETAIL);
  (api.createPilotPlan as any).mockResolvedValue(PLAN);
  (api.transitionPilotPlan as any).mockResolvedValue({ ...PLAN_DETAIL, status: "ready_for_review" });
  (api.reviewPilotPlan as any).mockResolvedValue({
    id: 9, pilotPlanId: 1, decision: "reviewed", note: "", decidedBy: "you", createdAt: "2026-06-01T09:00:00Z",
  });
});

describe("Phase 16G — Pilot Control Center page", () => {
  it("renders the page + safety banner", async () => {
    renderPage();
    expect(await screen.findByTestId("pilot-control-page")).toBeInTheDocument();
    expect(screen.getByTestId("pilot-control-safety-copy")).toHaveTextContent(
      /Internal control only — no live provider automation/i,
    );
  });

  it("renders the status summary counts", async () => {
    renderPage();
    expect(await screen.findByTestId("pilot-control-summary")).toBeInTheDocument();
  });

  it("renders the pilot plan list", async () => {
    renderPage();
    expect(await screen.findByTestId("pilot-plans-list")).toBeInTheDocument();
    expect(screen.getByTestId("pilot-plan-1")).toHaveTextContent("Joint pain internal pilot");
  });

  it("creates a pilot plan via the pilot API only", async () => {
    renderPage();
    await screen.findByTestId("pilot-create-form");
    fireEvent.change(screen.getByTestId("pilot-create-name"), { target: { value: "My pilot" } });
    fireEvent.click(screen.getByTestId("pilot-create-button"));
    await waitFor(() => expect(api.createPilotPlan).toHaveBeenCalledTimes(1));
    expect(api.createPilotPlan).toHaveBeenCalledWith(
      expect.objectContaining({ name: "My pilot", pilotType: "full_lifecycle" }),
    );
    // No provider/business path fired from the control page.
    expect(api.createImportOrder).not.toHaveBeenCalled();
  });

  it("opens a plan and renders the gate checklist + actions", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("pilot-plan-1"));
    expect(await screen.findByTestId("pilot-plan-detail")).toBeInTheDocument();
    expect(screen.getByTestId("pilot-gate-checklist")).toBeInTheDocument();
    expect(screen.getByTestId("pilot-plan-actions")).toBeInTheDocument();
    expect(screen.getByTestId("pilot-plan-events")).toBeInTheDocument();
  });

  it("a transition calls the internal pilot API only", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("pilot-plan-1"));
    await screen.findByTestId("pilot-plan-detail");
    fireEvent.click(screen.getByTestId("pilot-action-mark_ready"));
    await waitFor(() => expect(api.transitionPilotPlan).toHaveBeenCalledTimes(1));
    expect(api.transitionPilotPlan).toHaveBeenCalledWith(1, { action: "mark_ready" });
    expect(api.createImportOrder).not.toHaveBeenCalled();
  });

  it("records a Director note via the review API", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("pilot-plan-1"));
    await screen.findByTestId("pilot-plan-detail");
    fireEvent.click(screen.getByTestId("pilot-action-note"));
    await waitFor(() => expect(api.reviewPilotPlan).toHaveBeenCalledTimes(1));
  });

  it("renders the error state when summary fails", async () => {
    (api.getPilotControlSummary as any).mockRejectedValue(new Error("boom"));
    renderPage();
    expect(await screen.findByTestId("pilot-control-error")).toBeInTheDocument();
  });

  it("has no live provider action button", async () => {
    renderPage();
    await screen.findByTestId("pilot-create-form");
    expect(
      screen.queryByRole("button", {
        name: /send whatsapp|create live|book shipment|create payment link|capture|refund|start live automation/i,
      }),
    ).not.toBeInTheDocument();
  });
});

describe("Phase 16G — wiring", () => {
  it("registers the page route in App.tsx", () => {
    const appSrc = readFileSync(resolve(here, "../App.tsx"), "utf8");
    expect(appSrc).toContain('path="/operations/pilot-control"');
  });

  it("adds the sidebar link", () => {
    const sidebarSrc = readFileSync(resolve(here, "../components/layout/Sidebar.tsx"), "utf8");
    expect(sidebarSrc).toContain('to: "/operations/pilot-control"');
  });
});
