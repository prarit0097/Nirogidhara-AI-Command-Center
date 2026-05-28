import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Preserve real isApiError / ApiError; replace only the `api` object.
vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return {
    ...actual,
    api: {
      getImportsOverview: vi.fn(),
      getImportDatasets: vi.fn(),
      getImportDataset: vi.fn(),
      uploadImportDataset: vi.fn(),
      createImportCampaign: vi.fn(),
      getImportCampaigns: vi.fn(),
      getImportCampaignQueue: vi.fn(),
      recordImportOutcome: vi.fn(),
      createImportOrder: vi.fn(),
    },
  };
});

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

import DataImports from "@/pages/DataImports";
import ImportedCampaigns from "@/pages/ImportedCampaigns";
import { api } from "@/services/api";

const OVERVIEW = {
  datasetCount: 1,
  validContacts: 38,
  duplicateCount: 7,
  invalidCount: 5,
  activeCampaigns: 1,
  pendingCalls: 24,
  interestedRate: 31.5,
  orderCreatedCount: 4,
};

const DATASET = {
  id: 1,
  name: "Joint pain 2024",
  sourceLabel: "Old export",
  problemCategory: "Joint pain",
  originalFilename: "jp.csv",
  uploadedBy: "director",
  status: "ready" as const,
  totalRows: 50,
  validRows: 38,
  duplicateRows: 7,
  invalidRows: 5,
  importedRows: 0,
  createdAt: "2026-05-28T08:00:00Z",
  updatedAt: "2026-05-28T08:00:00Z",
};

const DATASET_DETAIL = {
  ...DATASET,
  errorSamples: [
    {
      rowNumber: 3,
      validationStatus: "invalid_phone" as const,
      reason: "bad phone",
      phoneLast4: "12",
    },
  ],
  problemBreakdown: [{ problemCategory: "Joint pain", count: 38 }],
  campaignIds: [],
};

const CAMPAIGN = {
  id: 1,
  name: "Joint pain campaign",
  datasetId: 1,
  problemCategory: "Joint pain",
  status: "active" as const,
  assignedTeam: "",
  totalContacts: 1,
  pendingCount: 1,
  completedCount: 0,
  interestedCount: 0,
  notInterestedCount: 0,
  callbackCount: 0,
  wrongNumberCount: 0,
  orderCreatedCount: 0,
  createdBy: "director",
  createdAt: "2026-05-28T08:10:00Z",
  updatedAt: "2026-05-28T08:10:00Z",
};

const QUEUE_ITEM = {
  id: 1,
  campaignId: 1,
  dataRowId: 1,
  name: "Ramesh",
  phoneMasked: "****5678",
  problemCategory: "Joint pain",
  city: "Mumbai",
  state: "MH",
  assignedAgent: null,
  status: "pending" as const,
  lastOutcome: "",
  callAttempts: 0,
  nextFollowUpAt: null,
  notes: "",
  escalationFlag: "",
  linkedOrderId: null,
  createdAt: "2026-05-28T08:10:00Z",
  updatedAt: "2026-05-28T08:10:00Z",
};

const renderImports = () =>
  render(
    <MemoryRouter>
      <DataImports />
    </MemoryRouter>,
  );

const renderCampaigns = () =>
  render(
    <MemoryRouter>
      <ImportedCampaigns />
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.clearAllMocks();
  (api.getImportsOverview as any).mockResolvedValue(OVERVIEW);
  (api.getImportDatasets as any).mockResolvedValue({ items: [DATASET], total: 1 });
  (api.uploadImportDataset as any).mockResolvedValue(DATASET_DETAIL);
  (api.createImportCampaign as any).mockResolvedValue(CAMPAIGN);
  (api.getImportCampaigns as any).mockResolvedValue({ items: [CAMPAIGN], total: 1 });
  (api.getImportCampaignQueue as any).mockResolvedValue({ items: [QUEUE_ITEM], total: 1 });
  (api.recordImportOutcome as any).mockResolvedValue({
    ...QUEUE_ITEM,
    status: "interested",
    lastOutcome: "interested",
  });
  (api.createImportOrder as any).mockResolvedValue({
    queueItem: { ...QUEUE_ITEM, status: "order_created", linkedOrderId: "NRG-20501" },
    orderId: "NRG-20501",
    orderStage: "Order Punched",
  });
});

describe("Phase 16D — Data Imports page", () => {
  it("renders the page, safety copy, and KPI summary", async () => {
    renderImports();
    expect(await screen.findByTestId("data-imports-page")).toBeInTheDocument();
    expect(screen.getByTestId("data-imports-safety-copy")).toHaveTextContent(
      /no whatsapp \/ payment \/ courier \/ vapi/i,
    );
    // KPI summary shows labels + the unique interested-rate value.
    expect(await screen.findByText("Valid contacts")).toBeInTheDocument();
    expect(screen.getByText("31.5%")).toBeInTheDocument();
  });

  it("uploads a CSV via the internal API and shows the validation summary", async () => {
    renderImports();
    await screen.findByTestId("data-imports-upload-form");

    fireEvent.change(screen.getByTestId("data-imports-name"), {
      target: { value: "Joint pain 2024" },
    });
    fireEvent.change(screen.getByTestId("data-imports-csv"), {
      target: { value: "name,phone\nRamesh,+919812345678" },
    });
    fireEvent.click(screen.getByTestId("data-imports-upload-submit"));

    await waitFor(() => expect(api.uploadImportDataset).toHaveBeenCalledTimes(1));
    expect(api.uploadImportDataset).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Joint pain 2024" }),
    );
    // Validation summary renders.
    expect(await screen.findByTestId("data-imports-result")).toBeInTheDocument();
  });

  it("lists datasets and creates a campaign from valid rows", async () => {
    renderImports();
    await screen.findByTestId("data-imports-table");
    expect(screen.getByText("Joint pain 2024")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("data-imports-create-campaign-1"));
    await waitFor(() => expect(api.createImportCampaign).toHaveBeenCalledTimes(1));
    expect(api.createImportCampaign).toHaveBeenCalledWith(1, expect.any(Object));
  });
});

describe("Phase 16D — Imported Campaigns page", () => {
  it("renders campaigns + the queue table", async () => {
    renderCampaigns();
    expect(await screen.findByTestId("imported-campaigns-page")).toBeInTheDocument();
    expect(await screen.findByTestId("imported-campaigns-table")).toBeInTheDocument();
    expect(await screen.findByTestId("imported-queue-table")).toBeInTheDocument();
    // Phone is masked, never full.
    expect(screen.getByText("****5678")).toBeInTheDocument();
  });

  it("records an outcome via the internal API only", async () => {
    renderCampaigns();
    await screen.findByTestId("imported-queue-table");

    fireEvent.change(screen.getByTestId("imported-queue-outcome-1"), {
      target: { value: "callback" },
    });
    fireEvent.click(screen.getByTestId("imported-queue-save-1"));

    await waitFor(() => expect(api.recordImportOutcome).toHaveBeenCalledTimes(1));
    expect(api.recordImportOutcome).toHaveBeenCalledWith(1, { outcome: "callback" });
  });

  it("shows Create order only for an interested item and calls the internal API", async () => {
    (api.getImportCampaignQueue as any).mockResolvedValue({
      items: [{ ...QUEUE_ITEM, status: "interested" }],
      total: 1,
    });
    renderCampaigns();
    await screen.findByTestId("imported-queue-table");

    const createBtn = await screen.findByTestId("imported-queue-create-order-1");
    fireEvent.click(createBtn);
    await waitFor(() => expect(api.createImportOrder).toHaveBeenCalledTimes(1));
    expect(api.createImportOrder).toHaveBeenCalledWith(1, {});
  });

  it("hides Create order for a non-interested (pending) item", async () => {
    renderCampaigns();
    await screen.findByTestId("imported-queue-table");
    expect(screen.queryByTestId("imported-queue-create-order-1")).not.toBeInTheDocument();
  });

  it("renders a clean empty state when there are no campaigns", async () => {
    (api.getImportCampaigns as any).mockResolvedValue({ items: [], total: 0 });
    renderCampaigns();
    expect(await screen.findByTestId("imported-campaigns-empty")).toBeInTheDocument();
  });
});
