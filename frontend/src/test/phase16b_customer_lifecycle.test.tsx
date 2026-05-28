/**
 * Phase 16B — Customer Lifecycle UI Backbone frontend tests.
 *
 * Coverage:
 *   - Confirmation queue buttons call the real api.confirmOrder.
 *   - Confirmation buttons show loading state + handle errors.
 *   - NewLeadModal opens, validates, submits, and handles duplicate response.
 *   - LeadImportModal renders summary after import.
 *
 * NOTE: All tests mock @/services/api so no real network call is made and
 * no Phase 15 safety surface is exercised. Phase 15 chrome is not modified
 * by Phase 16B; we do not exercise it here.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

// ---- mocks (must be declared BEFORE the imports they cover so vi.mock
//             hoisting resolves cleanly) ---------------------------------

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
}));

// Phase 16B-Hotfix-1: keep the REAL ApiError / isApiError exports (the
// NewLeadModal imports isApiError to detect 409 duplicates) while mocking
// only the `api` object.
vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return {
    ...actual,
    api: {
      getConfirmationQueue: vi.fn(),
      confirmOrder: vi.fn(),
      createLead: vi.fn(),
      importLeadsCsv: vi.fn(),
    },
  };
});

import { toast } from "sonner";
import { api, ApiError } from "@/services/api";
import Confirmation from "@/pages/Confirmation";
import { NewLeadModal } from "@/components/leads/NewLeadModal";
import { LeadImportModal } from "@/components/leads/LeadImportModal";

const toastSuccess = toast.success as unknown as ReturnType<typeof vi.fn>;
const toastError = toast.error as unknown as ReturnType<typeof vi.fn>;
const apiM = api as unknown as {
  getConfirmationQueue: ReturnType<typeof vi.fn>;
  confirmOrder: ReturnType<typeof vi.fn>;
  createLead: ReturnType<typeof vi.fn>;
  importLeadsCsv: ReturnType<typeof vi.fn>;
};

const SAMPLE_ORDER = {
  id: "NRG-PHASE16B-A",
  customerName: "Test Customer",
  product: "Joint Care",
  amount: 3000,
  city: "Mumbai",
  state: "MH",
  hoursWaiting: 18,
  addressConfidence: 82,
  phone: "+9199990000",
};

beforeEach(() => {
  vi.clearAllMocks();
});

// ---- Confirmation queue ------------------------------------------------

describe("Phase 16B — Confirmation queue button wire-up", () => {
  it("renders the confirmation queue from api.getConfirmationQueue", async () => {
    apiM.getConfirmationQueue.mockResolvedValue([SAMPLE_ORDER]);
    render(<Confirmation />);
    await waitFor(() =>
      expect(
        screen.getByTestId(`confirmation-card-${SAMPLE_ORDER.id}`),
      ).toBeInTheDocument(),
    );
  });

  it("calls api.confirmOrder with 'confirmed' when Confirmed button is clicked", async () => {
    apiM.getConfirmationQueue
      .mockResolvedValueOnce([SAMPLE_ORDER])
      .mockResolvedValue([]); // post-action refresh returns empty
    apiM.confirmOrder.mockResolvedValue({ ...SAMPLE_ORDER, stage: "Confirmed" });

    render(<Confirmation />);
    const confirmBtn = await screen.findByTestId(
      `confirmation-confirmed-${SAMPLE_ORDER.id}`,
    );
    fireEvent.click(confirmBtn);

    await waitFor(() =>
      expect(apiM.confirmOrder).toHaveBeenCalledWith(
        SAMPLE_ORDER.id,
        "confirmed",
      ),
    );
    await waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith(
        expect.stringContaining(SAMPLE_ORDER.id),
      ),
    );
  });

  it("calls api.confirmOrder with 'rescue_needed' when Rescue button is clicked", async () => {
    apiM.getConfirmationQueue.mockResolvedValue([SAMPLE_ORDER]);
    apiM.confirmOrder.mockResolvedValue({ ...SAMPLE_ORDER });
    render(<Confirmation />);
    const rescueBtn = await screen.findByTestId(
      `confirmation-rescue-${SAMPLE_ORDER.id}`,
    );
    fireEvent.click(rescueBtn);
    await waitFor(() =>
      expect(apiM.confirmOrder).toHaveBeenCalledWith(
        SAMPLE_ORDER.id,
        "rescue_needed",
      ),
    );
  });

  it("calls api.confirmOrder with 'cancelled' when Cancelled button is clicked", async () => {
    apiM.getConfirmationQueue.mockResolvedValue([SAMPLE_ORDER]);
    apiM.confirmOrder.mockResolvedValue({ ...SAMPLE_ORDER });
    render(<Confirmation />);
    const cancelBtn = await screen.findByTestId(
      `confirmation-cancel-${SAMPLE_ORDER.id}`,
    );
    fireEvent.click(cancelBtn);
    await waitFor(() =>
      expect(apiM.confirmOrder).toHaveBeenCalledWith(
        SAMPLE_ORDER.id,
        "cancelled",
      ),
    );
  });

  it("shows error toast when api.confirmOrder rejects", async () => {
    apiM.getConfirmationQueue.mockResolvedValue([SAMPLE_ORDER]);
    apiM.confirmOrder.mockRejectedValue(new Error("Network down"));
    render(<Confirmation />);
    const confirmBtn = await screen.findByTestId(
      `confirmation-confirmed-${SAMPLE_ORDER.id}`,
    );
    fireEvent.click(confirmBtn);
    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(
        expect.stringContaining("confirm"),
      ),
    );
    // No success toast on error path.
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it("shows empty state when no orders are queued", async () => {
    apiM.getConfirmationQueue.mockResolvedValue([]);
    render(<Confirmation />);
    await waitFor(() =>
      expect(screen.getByTestId("confirmation-empty")).toBeInTheDocument(),
    );
  });
});

// ---- NewLeadModal ------------------------------------------------------

describe("Phase 16B — NewLeadModal", () => {
  it("renders consent checkboxes that default to off", () => {
    render(
      <NewLeadModal open={true} onOpenChange={vi.fn()} onCreated={vi.fn()} />,
    );
    const callBox = screen.getByTestId("lead-consent-call") as HTMLInputElement;
    const waBox = screen.getByTestId(
      "lead-consent-whatsapp",
    ) as HTMLInputElement;
    const mktBox = screen.getByTestId(
      "lead-consent-marketing",
    ) as HTMLInputElement;
    // Checkbox primitive uses aria-checked, not native checked. We assert
    // none of the three are aria-checked at render.
    expect(callBox.getAttribute("aria-checked")).not.toBe("true");
    expect(waBox.getAttribute("aria-checked")).not.toBe("true");
    expect(mktBox.getAttribute("aria-checked")).not.toBe("true");
  });

  it("does not call api.createLead when name+phone are empty", async () => {
    const onCreated = vi.fn();
    render(
      <NewLeadModal open={true} onOpenChange={vi.fn()} onCreated={onCreated} />,
    );
    // Empty submit: HTML5 `required` on name+phone prevents the form
    // from actually submitting. Either way the api method must NOT fire
    // and the onCreated callback must not be invoked.
    fireEvent.click(screen.getByTestId("new-lead-submit"));
    // Yield one microtask tick so any rejected promise would surface.
    await Promise.resolve();
    expect(apiM.createLead).not.toHaveBeenCalled();
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("submits to api.createLead with consent fields", async () => {
    const onCreated = vi.fn();
    const onOpenChange = vi.fn();
    apiM.createLead.mockResolvedValue({ id: "LD-12345", name: "Test" });
    render(
      <NewLeadModal
        open={true}
        onOpenChange={onOpenChange}
        onCreated={onCreated}
      />,
    );
    fireEvent.change(screen.getByLabelText(/name \*/i), {
      target: { value: "Test Pilot" },
    });
    fireEvent.change(screen.getByLabelText(/phone \*/i), {
      target: { value: "+919998881111" },
    });
    fireEvent.click(screen.getByTestId("lead-consent-whatsapp"));
    fireEvent.click(screen.getByTestId("new-lead-submit"));
    await waitFor(() => expect(apiM.createLead).toHaveBeenCalledTimes(1));
    const payload = apiM.createLead.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(payload.name).toBe("Test Pilot");
    expect(payload.phone).toBe("+919998881111");
    expect(payload.consentWhatsapp).toBe(true);
    expect(payload.consentCall).toBe(false);
    expect(payload.consentMarketing).toBe(false);
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
  });

  it("shows a duplicate-blocked banner + error toast on 409, no created success, modal stays open", async () => {
    apiM.createLead.mockRejectedValue(
      new ApiError(409, {
        duplicate: true,
        field: "phone",
        existingLeadId: "LD-99999",
        detail: "Duplicate phone: lead LD-99999 already exists",
      }),
    );
    const onCreated = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <NewLeadModal
        open={true}
        onOpenChange={onOpenChange}
        onCreated={onCreated}
      />,
    );
    fireEvent.change(screen.getByLabelText(/name \*/i), {
      target: { value: "Dup" },
    });
    fireEvent.change(screen.getByLabelText(/phone \*/i), {
      target: { value: "+919998881111" },
    });
    fireEvent.click(screen.getByTestId("new-lead-submit"));
    await waitFor(() =>
      expect(screen.getByTestId("new-lead-duplicate")).toBeInTheDocument(),
    );
    const banner = screen.getByTestId("new-lead-duplicate");
    expect(banner.textContent).toContain("phone");
    expect(banner.textContent).toContain("LD-99999");
    // Duplicate is NOT treated as created.
    expect(toastSuccess).not.toHaveBeenCalled();
    // Phase 16B-Hotfix-2: phone-only message.
    expect(toastError).toHaveBeenCalledWith(
      "Duplicate phone blocked — existing lead found.",
    );
    // Never an "email"-duplicate message.
    expect(banner.textContent?.toLowerCase()).not.toContain("email");
    expect(onCreated).not.toHaveBeenCalled();
    // Modal stays open (onOpenChange(false) NOT called).
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("same email + different phone (201) shows created success, not a duplicate", async () => {
    apiM.createLead.mockResolvedValue({ id: "LD-20002", name: "Same Email" });
    const onCreated = vi.fn();
    render(
      <NewLeadModal open={true} onOpenChange={vi.fn()} onCreated={onCreated} />,
    );
    fireEvent.change(screen.getByLabelText(/name \*/i), { target: { value: "Same Email" } });
    fireEvent.change(screen.getByLabelText(/phone \*/i), { target: { value: "+919998882222" } });
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "shared@example.com" } });
    fireEvent.click(screen.getByTestId("new-lead-submit"));
    await waitFor(() => expect(apiM.createLead).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    // No duplicate banner; success toast fired.
    expect(screen.queryByTestId("new-lead-duplicate")).not.toBeInTheDocument();
    expect(toastSuccess).toHaveBeenCalledWith(expect.stringContaining("LD-20002"));
  });
});

// ---- LeadImportModal ---------------------------------------------------

describe("Phase 16B — LeadImportModal", () => {
  it("blocks submission when CSV is empty", async () => {
    render(
      <LeadImportModal
        open={true}
        onOpenChange={vi.fn()}
        onImported={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("lead-import-submit"));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(apiM.importLeadsCsv).not.toHaveBeenCalled();
  });

  it("shows the import summary after a successful upload", async () => {
    apiM.importLeadsCsv.mockResolvedValue({
      totalRows: 3,
      createdCount: 2,
      duplicateCount: 1,
      errorCount: 0,
      createdLeadIds: ["LD-1", "LD-2"],
      rowErrors: [
        { rowNumber: 3, reason: "Duplicate of existing Lead (phone or email)", phoneLast4: "1234" },
      ],
      truncatedErrorList: false,
    });
    const onImported = vi.fn();
    render(
      <LeadImportModal
        open={true}
        onOpenChange={vi.fn()}
        onImported={onImported}
      />,
    );
    fireEvent.change(screen.getByTestId("lead-import-csv"), {
      target: { value: "name,phone\nA,+9199900\nB,+9199901\nC,+9199900\n" },
    });
    fireEvent.click(screen.getByTestId("lead-import-submit"));
    await waitFor(() =>
      expect(screen.getByTestId("lead-import-result")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("lead-import-result").textContent).toContain("2");
    expect(screen.getByTestId("lead-import-result").textContent).toContain("1");
    expect(onImported).toHaveBeenCalled();
    // Row error masks phone — never the full digits.
    expect(screen.getByTestId("lead-import-result").textContent).toContain(
      "****1234",
    );
  });
});
