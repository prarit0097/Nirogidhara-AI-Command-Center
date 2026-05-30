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
      getPilotReadiness: vi.fn(),
      getPilotDryRuns: vi.fn(),
      createPilotDryRun: vi.fn(),
      reviewPilotDryRun: vi.fn(),
      // Representative provider/business methods — must never be called here.
      createImportOrder: vi.fn(),
      getPaymentLogisticsReadiness: vi.fn(),
    },
  };
});

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

import PilotReadiness from "@/pages/PilotReadiness";
import { api } from "@/services/api";

const here = dirname(fileURLToPath(import.meta.url));

const READINESS = {
  safety: {
    aiPaused: true,
    sandboxOn: false,
    syncLive: true,
    providerLiveActionsLocked: true,
    phase15ShellFrozen: true,
    phase: "16F",
  },
  automationFlags: { aiCallingEnabled: false, whatsappProvider: "mock", vapiMode: "mock" },
  paymentReadiness: { provider: "razorpay", label: "Razorpay", mode: "mock", rawMode: "mock", configured: true, secretRefsPresent: {}, liveEnabled: false, liveGateRequired: true, liveGatePresent: false, status: "ready" as const, blockedReasons: [], safeActions: [] },
  payuReadiness: { provider: "payu", label: "PayU", mode: "unavailable", rawMode: "unavailable", configured: false, secretRefsPresent: {}, liveEnabled: false, liveGateRequired: true, liveGatePresent: false, status: "unavailable" as const, blockedReasons: [], safeActions: [] },
  logisticsReadiness: { provider: "delhivery", label: "Delhivery", mode: "mock", rawMode: "mock", configured: true, secretRefsPresent: {}, liveEnabled: false, liveGateRequired: true, liveGatePresent: false, status: "ready" as const, blockedReasons: [], safeActions: [] },
  claimVault: { status: "warning" as const, message: "demo seeds", demoCount: 8, total: 8 },
  teamRoles: { status: "pass" as const, message: "ok", assignedRoles: ["director_admin"] },
  dataCounts: { leads: 42, customers: 18, orders: 12, importedCampaigns: 1 },
  gates: [
    { key: "lead_customer_data", label: "Lead / Customer data ready", status: "pass" as const, detail: "ok" },
    { key: "payment_readiness", label: "Payment readiness (live blocked)", status: "blocked" as const, detail: "blocked" },
    { key: "shipment_readiness", label: "Shipment readiness (live blocked)", status: "blocked" as const, detail: "blocked" },
    { key: "whatsapp_automation", label: "WhatsApp live automation blocked", status: "blocked" as const, detail: "blocked" },
    { key: "vapi_ai_calling", label: "Vapi / AI calling blocked", status: "blocked" as const, detail: "blocked" },
    { key: "safety_state", label: "Safety state", status: "pass" as const, detail: "ok" },
  ],
  blockedLiveActions: [
    "Live Razorpay/PayU payment link — blocked.",
    "Live Delhivery AWB — blocked.",
    "WhatsApp — blocked.",
    "Vapi — blocked.",
  ],
  signoffChecklistKeys: [
    { key: "pilot_team_selected", label: "Pilot team selected" },
    { key: "live_provider_gate_not_approved", label: "Live provider gate NOT approved yet" },
  ],
  noSideEffect: true,
  generatedByProvider: false as const,
};

const DRY_RUNS = {
  items: [
    {
      id: 1,
      name: "Full lifecycle dry-run",
      scenarioType: "full_lifecycle" as const,
      status: "warning" as const,
      resultSummary: "ok",
      selectedLeadId: null,
      selectedCustomerId: null,
      selectedOrderId: null,
      selectedImportCampaignId: null,
      selectedQueueItemId: null,
      createdBy: "director",
      providerActionsAttempted: false,
      providerActionsBlocked: true,
      createdAt: "2026-05-30T08:00:00Z",
      updatedAt: "2026-05-30T08:00:00Z",
    },
  ],
  total: 1,
};

const renderPage = () =>
  render(
    <MemoryRouter>
      <PilotReadiness />
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.clearAllMocks();
  (api.getPilotReadiness as any).mockResolvedValue(READINESS);
  (api.getPilotDryRuns as any).mockResolvedValue(DRY_RUNS);
  (api.createPilotDryRun as any).mockResolvedValue({
    ...DRY_RUNS.items[0],
    status: "passed",
  });
});

describe("Phase 16F — Pilot Readiness page", () => {
  it("renders the page + safety banner", async () => {
    renderPage();
    expect(await screen.findByTestId("pilot-readiness-page")).toBeInTheDocument();
    expect(screen.getByTestId("pilot-safety-copy")).toHaveTextContent(
      /does NOT send WhatsApp, take a payment, book a shipment, place a call/i,
    );
  });

  it("renders the gate matrix with blocked provider gates", async () => {
    renderPage();
    expect(await screen.findByTestId("pilot-gate-matrix")).toBeInTheDocument();
    expect(screen.getByTestId("pilot-gate-payment_readiness")).toHaveTextContent(/blocked/i);
    expect(screen.getByTestId("pilot-gate-shipment_readiness")).toHaveTextContent(/blocked/i);
    expect(screen.getByTestId("pilot-gate-whatsapp_automation")).toHaveTextContent(/blocked/i);
    expect(screen.getByTestId("pilot-gate-vapi_ai_calling")).toHaveTextContent(/blocked/i);
  });

  it("runs an internal dry-run via the pilot API only", async () => {
    renderPage();
    await screen.findByTestId("pilot-run-form");
    fireEvent.change(screen.getByTestId("pilot-run-name"), {
      target: { value: "My pilot" },
    });
    fireEvent.click(screen.getByTestId("pilot-run-button"));
    await waitFor(() => expect(api.createPilotDryRun).toHaveBeenCalledTimes(1));
    expect(api.createPilotDryRun).toHaveBeenCalledWith(
      expect.objectContaining({ name: "My pilot", scenarioType: "full_lifecycle" }),
    );
    // No provider/business path fired from the pilot page.
    expect(api.createImportOrder).not.toHaveBeenCalled();
  });

  it("renders recent dry-runs", async () => {
    renderPage();
    expect(await screen.findByTestId("pilot-dry-runs-table")).toBeInTheDocument();
    expect(screen.getByText("Full lifecycle dry-run")).toBeInTheDocument();
  });

  it("renders the error state when readiness fails", async () => {
    (api.getPilotReadiness as any).mockRejectedValue(new Error("boom"));
    renderPage();
    expect(await screen.findByTestId("pilot-readiness-error")).toBeInTheDocument();
  });

  it("has no live provider action button", async () => {
    renderPage();
    await screen.findByTestId("pilot-run-form");
    expect(
      screen.queryByRole("button", { name: /send whatsapp|create live|book shipment|call customer|capture|refund/i }),
    ).not.toBeInTheDocument();
    // The only action is the internal dry-run.
    expect(screen.getByTestId("pilot-run-button")).toHaveTextContent(/internal dry-run/i);
  });
});

describe("Phase 16F — wiring", () => {
  it("registers the page route in App.tsx", () => {
    const appSrc = readFileSync(resolve(here, "../App.tsx"), "utf8");
    expect(appSrc).toContain('path="/operations/pilot-readiness"');
  });

  it("adds the sidebar link", () => {
    const sidebarSrc = readFileSync(resolve(here, "../components/layout/Sidebar.tsx"), "utf8");
    expect(sidebarSrc).toContain('to: "/operations/pilot-readiness"');
  });
});
