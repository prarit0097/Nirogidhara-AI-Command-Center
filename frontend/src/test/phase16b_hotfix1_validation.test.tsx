/**
 * Phase 16B-Hotfix-1 — Customer Lifecycle UI validation fixes.
 *
 * Coverage:
 *   - safeMutate surfaces a real HTTP error response as a typed ApiError
 *     (no optimistic-mock fallback that would fake success).
 *   - Leads table renders an S.N. column with a display index over the
 *     current filtered list (not the database id).
 *   - Orders page exposes a discoverable transition affordance: clicking an
 *     order card opens the detail panel; the safe transition button calls
 *     api.transitionOrder; success refreshes the list; failure shows an
 *     error toast; no provider/WhatsApp/payment/courier method is called.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

// ---- mocks -------------------------------------------------------------

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
}));

vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return {
    ...actual,
    api: {
      getLeads: vi.fn(),
      getOrders: vi.fn(),
      transitionOrder: vi.fn(),
      // Outbound provider entrypoints — must NEVER be called from these pages.
      confirmOrder: vi.fn(),
      createPaymentLink: vi.fn(),
      sendWhatsAppTemplate: vi.fn(),
      createShipment: vi.fn(),
      triggerCall: vi.fn(),
    },
  };
});

import { toast } from "sonner";
import { api } from "@/services/api";
import Leads from "@/pages/Leads";
import Orders from "@/pages/Orders";

const toastSuccess = toast.success as unknown as ReturnType<typeof vi.fn>;
const toastError = toast.error as unknown as ReturnType<typeof vi.fn>;
const apiM = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const SAMPLE_LEADS = [
  { id: "LD-10300", name: "Alpha", phone: "+910000000001", state: "MH", city: "Mumbai", language: "Hinglish", source: "Manual", campaign: "", productInterest: "Joint Care", status: "New", quality: "Warm", qualityScore: 50, assignee: "", duplicate: false, createdAt: "just now" },
  { id: "LD-10301", name: "Bravo", phone: "+910000000002", state: "DL", city: "Delhi", language: "Hindi", source: "Meta Ads", campaign: "C1", productInterest: "Immunity", status: "Interested", quality: "Hot", qualityScore: 80, assignee: "Vaani-3", duplicate: false, createdAt: "1h ago" },
];

const SAMPLE_ORDERS = [
  { id: "NRG-HF1-A", customerName: "Order One", phone: "+910000000010", product: "Joint Care", quantity: 1, amount: 3000, discountPct: 0, advancePaid: false, advanceAmount: 0, paymentStatus: "Pending", state: "MH", city: "Mumbai", rtoRisk: "Low", rtoScore: 10, agent: "Vaani-3", ageHours: 4, stage: "New Lead" },
];

beforeEach(() => {
  vi.clearAllMocks();
});

// ---- safeMutate ApiError semantics -------------------------------------

describe("Phase 16B-Hotfix-1 — safeMutate surfaces HTTP errors (no fake success)", () => {
  it("throws ApiError on a 409 response instead of returning an optimistic mock", async () => {
    // Use the REAL api module here (not the page mock) to exercise safeMutate.
    const realApi = await vi.importActual<typeof import("@/services/api")>(
      "@/services/api",
    );
    const originalFetch = global.fetch;
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({
        duplicate: true,
        field: "phone",
        existingLeadId: "LD-55555",
        detail: "Duplicate phone",
      }),
    }) as unknown as typeof fetch;

    try {
      await expect(
        realApi.api.createLead({ name: "Dup", phone: "+910000000099" }),
      ).rejects.toMatchObject({ httpStatus: 409, isApiError: true });
    } finally {
      global.fetch = originalFetch;
    }
  });

  it("still falls back to optimistic mock on a genuine network failure", async () => {
    const realApi = await vi.importActual<typeof import("@/services/api")>(
      "@/services/api",
    );
    const originalFetch = global.fetch;
    global.fetch = vi.fn().mockRejectedValue(new Error("network down")) as unknown as typeof fetch;
    try {
      // No throw — offline resilience preserved (returns an optimistic Lead).
      const lead = await realApi.api.createLead({ name: "Offline", phone: "+910000000098" });
      expect(lead).toBeTruthy();
      expect(typeof lead.id).toBe("string");
    } finally {
      global.fetch = originalFetch;
    }
  });
});

// ---- Leads S.N. column -------------------------------------------------

describe("Phase 16B-Hotfix-1 — Leads S.N. column", () => {
  it("renders S.N. header and a display-index serial per row", async () => {
    apiM.getLeads.mockResolvedValue(SAMPLE_LEADS);
    render(<Leads />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    // Header present.
    expect(screen.getByText("S.N.")).toBeInTheDocument();
    // Serial 1 + 2 visible, derived from list index, not the DB id.
    expect(screen.getByTestId("lead-sn-1").textContent).toBe("1");
    expect(screen.getByTestId("lead-sn-2").textContent).toBe("2");
    // S.N. is NOT the database id.
    expect(screen.getByTestId("lead-sn-1").textContent).not.toContain("LD-");
  });

  it("S.N. re-indexes against the filtered result set", async () => {
    apiM.getLeads.mockResolvedValue(SAMPLE_LEADS);
    render(<Leads />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    // Filter to "Interested" status → only Bravo remains, and its S.N. is 1.
    fireEvent.click(screen.getByRole("button", { name: "Interested" }));
    await waitFor(() => expect(screen.queryByText("Alpha")).not.toBeInTheDocument());
    expect(screen.getByTestId("lead-sn-1").textContent).toBe("1");
    expect(screen.queryByTestId("lead-sn-2")).not.toBeInTheDocument();
  });
});

// ---- Orders transition discoverability ---------------------------------

describe("Phase 16B-Hotfix-1 — Orders transition discoverability", () => {
  it("renders the discoverability hint with the safe-copy note", async () => {
    apiM.getOrders.mockResolvedValue(SAMPLE_ORDERS);
    render(<Orders />);
    await waitFor(() =>
      expect(screen.getByTestId("orders-transition-hint")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("orders-transition-hint").textContent).toContain(
      "no WhatsApp / payment / courier action",
    );
  });

  it("opens the detail panel when an order card is clicked", async () => {
    apiM.getOrders.mockResolvedValue(SAMPLE_ORDERS);
    render(<Orders />);
    const card = await screen.findByTestId("order-card-NRG-HF1-A");
    fireEvent.click(card);
    await waitFor(() =>
      expect(
        screen.getByTestId("order-transition-options-NRG-HF1-A"),
      ).toBeInTheDocument(),
    );
  });

  it("calls api.transitionOrder, refreshes, and fires NO provider methods", async () => {
    apiM.getOrders
      .mockResolvedValueOnce(SAMPLE_ORDERS) // initial
      .mockResolvedValue([{ ...SAMPLE_ORDERS[0], stage: "Interested" }]); // refresh
    apiM.transitionOrder.mockResolvedValue({ ...SAMPLE_ORDERS[0], stage: "Interested" });

    render(<Orders />);
    const card = await screen.findByTestId("order-card-NRG-HF1-A");
    fireEvent.click(card);
    const btn = await screen.findByTestId(
      "order-transition-NRG-HF1-A-interested",
    );
    fireEvent.click(btn);

    await waitFor(() =>
      expect(apiM.transitionOrder).toHaveBeenCalledWith("NRG-HF1-A", "Interested"),
    );
    await waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith(
        expect.stringContaining("Interested"),
      ),
    );
    // Refresh fired (getOrders called at least twice: mount + post-transition).
    expect(apiM.getOrders.mock.calls.length).toBeGreaterThanOrEqual(2);
    // NO provider / outbound method called from this flow.
    expect(apiM.createPaymentLink).not.toHaveBeenCalled();
    expect(apiM.sendWhatsAppTemplate).not.toHaveBeenCalled();
    expect(apiM.createShipment).not.toHaveBeenCalled();
    expect(apiM.triggerCall).not.toHaveBeenCalled();
    expect(apiM.confirmOrder).not.toHaveBeenCalled();
  });

  it("shows an error toast when the transition API rejects", async () => {
    apiM.getOrders.mockResolvedValue(SAMPLE_ORDERS);
    apiM.transitionOrder.mockRejectedValue(new Error("Invalid transition"));
    render(<Orders />);
    const card = await screen.findByTestId("order-card-NRG-HF1-A");
    fireEvent.click(card);
    const btn = await screen.findByTestId(
      "order-transition-NRG-HF1-A-interested",
    );
    fireEvent.click(btn);
    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(
        expect.stringContaining("Invalid transition"),
      ),
    );
  });
});
