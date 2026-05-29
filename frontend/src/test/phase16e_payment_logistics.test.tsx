import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return {
    ...actual,
    api: {
      getPaymentLogisticsReadiness: vi.fn(),
      getPaymentLogisticsRecentEvents: vi.fn(),
    },
  };
});

import PaymentLogistics from "@/pages/PaymentLogistics";
import { api } from "@/services/api";

const here = dirname(fileURLToPath(import.meta.url));

const READINESS = {
  safety: {
    aiPaused: true,
    sandboxOn: false,
    providerLiveActionsLocked: true,
    hardeningMode: true,
    phase: "16E",
  },
  payments: [
    {
      provider: "razorpay",
      label: "Razorpay",
      mode: "mock",
      rawMode: "mock",
      configured: true,
      secretRefsPresent: { keyId: false, keySecret: false, webhookSecret: false },
      liveEnabled: false,
      liveGateRequired: true,
      liveGatePresent: false,
      status: "ready" as const,
      blockedReasons: [],
      safeActions: ["View readiness (mock — no network)."],
    },
    {
      provider: "payu",
      label: "PayU",
      mode: "unavailable",
      rawMode: "unavailable",
      configured: false,
      secretRefsPresent: { merchantKey: false, salt: false },
      liveEnabled: false,
      liveGateRequired: true,
      liveGatePresent: false,
      status: "unavailable" as const,
      blockedReasons: ["PayU adapter is not implemented (deferred)."],
      safeActions: [],
    },
  ],
  logistics: [
    {
      provider: "delhivery",
      label: "Delhivery",
      mode: "mock",
      rawMode: "mock",
      configured: true,
      secretRefsPresent: { apiToken: false, apiBaseUrl: false },
      liveEnabled: false,
      liveGateRequired: true,
      liveGatePresent: false,
      status: "ready" as const,
      blockedReasons: [],
      safeActions: ["Create a mock shipment via the existing operations flow (no network)."],
    },
  ],
  orderWorkflowGates: {
    paymentGate: {
      liveEnabled: false,
      liveGateRequired: true,
      liveGatePresent: false,
      note: "Live payment blocked without a Director live gate.",
    },
    shipmentGate: {
      liveEnabled: false,
      liveGateRequired: true,
      liveGatePresent: false,
      note: "Live Delhivery booking blocked without a Director live gate.",
    },
  },
  noSideEffect: true,
  generatedByProvider: false as const,
};

const EVENTS = { payments: [], shipments: [], paymentTotal: 0, shipmentTotal: 0 };

const renderPage = () =>
  render(
    <MemoryRouter>
      <PaymentLogistics />
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.clearAllMocks();
  (api.getPaymentLogisticsReadiness as any).mockResolvedValue(READINESS);
  (api.getPaymentLogisticsRecentEvents as any).mockResolvedValue(EVENTS);
});

describe("Phase 16E — Payment & Logistics page", () => {
  it("renders the page + safety copy", async () => {
    renderPage();
    expect(await screen.findByTestId("payment-logistics-page")).toBeInTheDocument();
    expect(screen.getByTestId("payment-logistics-safety-copy")).toHaveTextContent(
      /no whatsapp \/ payment \/ courier \/ vapi/i,
    );
  });

  it("renders Razorpay, PayU, and Delhivery readiness cards", async () => {
    renderPage();
    expect(await screen.findByTestId("provider-card-razorpay")).toBeInTheDocument();
    expect(screen.getByTestId("provider-card-payu")).toBeInTheDocument();
    expect(screen.getByTestId("provider-card-delhivery")).toBeInTheDocument();
    // PayU shows unavailable status.
    expect(screen.getByTestId("provider-status-payu")).toHaveTextContent(/unavailable/i);
  });

  it("renders blocked reasons for a blocked provider", async () => {
    (api.getPaymentLogisticsReadiness as any).mockResolvedValue({
      ...READINESS,
      logistics: [
        {
          ...READINESS.logistics[0],
          mode: "live-gated",
          status: "blocked",
          liveEnabled: false,
          blockedReasons: ["Live Delhivery booking blocked — Director live gate required."],
        },
      ],
    });
    renderPage();
    expect(
      await screen.findByText(/Live Delhivery booking blocked — Director live gate required\./i),
    ).toBeInTheDocument();
    expect(screen.getByTestId("provider-status-delhivery")).toHaveTextContent(/blocked/i);
  });

  it("renders the error state when readiness fails", async () => {
    (api.getPaymentLogisticsReadiness as any).mockRejectedValue(new Error("boom"));
    renderPage();
    expect(await screen.findByTestId("payment-logistics-error")).toBeInTheDocument();
  });

  it("renders NO live action button (live actions disabled)", async () => {
    renderPage();
    await screen.findByTestId("provider-card-razorpay");
    // No button that would trigger a live charge / booking exists.
    expect(screen.queryByRole("button", { name: /create live|capture|refund|book live|go live/i })).not.toBeInTheDocument();
  });
});

describe("Phase 16E — wiring", () => {
  it("registers the page route in App.tsx", () => {
    const appSrc = readFileSync(resolve(here, "../App.tsx"), "utf8");
    expect(appSrc).toContain('path="/operations/payment-logistics"');
  });

  it("adds the sidebar link", () => {
    const sidebarSrc = readFileSync(
      resolve(here, "../components/layout/Sidebar.tsx"),
      "utf8",
    );
    expect(sidebarSrc).toContain('to: "/operations/payment-logistics"');
  });
});
