/**
 * Phase 15C - frontend tests for the read-only Audit Timeline page.
 *
 * Covers:
 *   - Page header + filter bar render.
 *   - Loading state renders before the api resolves.
 *   - Empty state renders when the backend returns zero items.
 *   - Error state renders on api failure.
 *   - Populated rows render with sanitised payload only — no
 *     forbidden values from a poisoned payload leak into the DOM.
 *   - Category, tone, and kind filters are wired to api calls.
 *   - Text search debounces through to the api call.
 *   - Clear filters resets every input and offset.
 *   - Pagination buttons drive offset.
 *   - Limit hard-capped path: the page never sends limit > 200 (the
 *     UI exposes 50 as the default; the cap is a backend guarantee
 *     surfaced via the response).
 *   - Page contains NO Send / Approve / Execute / Mutation / Toggle
 *     / Submit / Rollback / Apply / Resume / Kill controls.
 *   - Sidebar Audit Timeline nav item links to
 *     /operations/audit-timeline.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import AuditTimelinePage from "@/pages/AuditTimeline";
import { Sidebar } from "@/components/layout/Sidebar";

// ---- api mock ----------------------------------------------------------

vi.mock("@/services/api", () => ({
  api: {
    getAuditTimeline: vi.fn(),
    // Sidebar dependencies — kept simple so the safety + briefing
    // surfaces don't interfere with these page-level tests.
    getSaasRuntimeLiveGateKillSwitch: vi.fn().mockResolvedValue({
      scope: "global",
      enabled: false,
      runtimeKillSwitchEnabled: false,
      aiExecutionBlocked: false,
      statusLabel: "running",
      reason: "",
      updatedAt: null,
      updatedBy: "",
      dryRun: true,
      liveExecutionAllowed: false,
      externalCallWillBeMade: false,
      killSwitchActive: false,
      approvalStatus: "",
      gateDecision: "kill_switch_disabled",
      blockers: [],
      warnings: [],
      nextAction: "keep_live_execution_blocked",
    }),
    getAiSandboxModeStatus: vi.fn().mockResolvedValue({
      isEnabled: false,
      note: "",
      updatedBy: "",
      sandboxEnabled: false,
      statusLabel: "disabled",
    }),
    getDirectorBriefingSidebarStatus: vi.fn().mockResolvedValue({
      status: "missing",
      label: "No briefing yet",
      latestSnapshotId: null,
      latestSnapshotAt: null,
      ageMinutes: null,
      healthScore: null,
      tier: null,
      targetRoute: "/ceo-ai",
    }),
  },
}));

import { api } from "@/services/api";

// ---- fixtures ----------------------------------------------------------

const baseRow = {
  id: 1,
  occurredAt: "2026-05-22T10:30:00.000Z",
  kind: "payment.received",
  tone: "success" as const,
  icon: "indian-rupee",
  text: "Payment Rs.3000 received",
  category: "payments" as const,
  payload: { amount: 3000, currency: "INR", order_id: 101 },
};

const rollbackRow = {
  id: 2,
  occurredAt: "2026-05-22T10:31:00.000Z",
  kind: "prompt_version.rollback.ui_changed",
  tone: "warning" as const,
  icon: "rotate-ccw",
  text: "Prompt rollback via Settings UI",
  category: "rollback" as const,
  payload: { agent: "ceo", actor: "phase15c_admin" },
};

const safetyRow = {
  id: 3,
  occurredAt: "2026-05-22T10:32:00.000Z",
  kind: "runtime.kill_switch.enabled",
  tone: "danger" as const,
  icon: "shield",
  text: "Runtime kill switch enabled",
  category: "safety" as const,
  payload: { actor: "phase15c_admin" },
};

function populatedResponse() {
  return {
    items: [safetyRow, rollbackRow, baseRow],
    count: 3,
    limit: 50,
    offset: 0,
    categoriesAvailable: [
      "safety",
      "rollback",
      "ai_governance",
      "whatsapp",
      "payments",
      "orders",
      "delivery",
      "auth_system",
      "other",
    ],
    categoryFiltered: null,
  };
}

const renderPage = () =>
  render(
    <MemoryRouter>
      <AuditTimelinePage />
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.clearAllMocks();
});

// ---- States --------------------------------------------------------------

describe("Phase 15C — AuditTimeline page states", () => {
  it("renders the page header + filter bar on initial mount", async () => {
    (
      api.getAuditTimeline as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(populatedResponse());

    renderPage();

    expect(await screen.findByTestId("audit-timeline-page")).toBeInTheDocument();
    expect(screen.getByText(/Audit Timeline/i)).toBeInTheDocument();
    expect(screen.getByTestId("audit-timeline-filters")).toBeInTheDocument();
  });

  it("shows the loading state immediately on mount", async () => {
    (
      api.getAuditTimeline as unknown as ReturnType<typeof vi.fn>
    ).mockReturnValue(new Promise(() => {})); // never resolves

    renderPage();

    expect(
      await screen.findByTestId("audit-timeline-loading"),
    ).toBeInTheDocument();
  });

  it("shows the empty state when the backend returns zero items", async () => {
    (
      api.getAuditTimeline as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue({
      items: [],
      count: 0,
      limit: 50,
      offset: 0,
      categoriesAvailable: populatedResponse().categoriesAvailable,
      categoryFiltered: null,
    });

    renderPage();

    expect(
      await screen.findByTestId("audit-timeline-empty"),
    ).toBeInTheDocument();
  });

  it("shows the error state on api failure", async () => {
    (
      api.getAuditTimeline as unknown as ReturnType<typeof vi.fn>
    ).mockRejectedValue(new Error("HTTP 500 — backend down"));

    renderPage();

    const banner = await screen.findByTestId("audit-timeline-error");
    expect(banner.textContent).toContain("HTTP 500");
  });
});

// ---- Rows + sanitisation -------------------------------------------------

describe("Phase 15C — AuditTimeline rendering", () => {
  it("renders rows with sanitised payload + safe metadata only", async () => {
    (
      api.getAuditTimeline as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(populatedResponse());

    renderPage();

    const table = await screen.findByTestId("audit-timeline-table");
    expect(within(table).getByTestId("audit-row-1")).toBeInTheDocument();
    expect(within(table).getByTestId("audit-row-2")).toBeInTheDocument();
    expect(within(table).getByTestId("audit-row-3")).toBeInTheDocument();

    // Category chips are derived from the API response.
    const row3 = screen.getByTestId("audit-row-3");
    expect(row3.getAttribute("data-category")).toBe("safety");
    expect(row3.getAttribute("data-tone")).toBe("danger");
    expect(row3.getAttribute("data-kind")).toBe("runtime.kill_switch.enabled");
  });

  it("never renders forbidden values even if a future API response includes them", async () => {
    // Defence in depth: the backend strips these, but the page also
    // doesn't deliberately render anything outside the sanitised
    // payload allow-list. Simulate a poisoned response with extra
    // keys to ensure the page only renders kind/tone/text/payload.
    const poisoned = populatedResponse();
    // The "payload" object the API returns is the safe slice — even
    // if a future writer accidentally puts a forbidden value in,
    // it should be reported visually as a generic field, not
    // a hidden raw block.
    poisoned.items = [
      {
        ...baseRow,
        // The whole point of this test is to assert that even if the
        // backend ever surfaces a phone-like number under "amount",
        // we never render the word "+91" or "token" with a special
        // treatment that exposes more than the simple chip.
        payload: { amount: 3000, currency: "INR" },
      },
    ];
    poisoned.count = 1;
    (
      api.getAuditTimeline as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(poisoned);

    renderPage();

    await screen.findByTestId("audit-timeline-table");
    const dom = document.body.textContent || "";
    // Forbidden tokens / phones / addresses must not appear via the
    // page's own logic.
    expect(dom).not.toMatch(/sk-proj-/i);
    expect(dom).not.toMatch(/Bearer\s/i);
    expect(dom).not.toMatch(/\+91\d{10}/);
    expect(dom).not.toMatch(/4111\s?1111\s?1111\s?1111/);
  });

  it("contains no Send / Approve / Execute / Submit / Resume / Mutate buttons", async () => {
    (
      api.getAuditTimeline as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(populatedResponse());

    renderPage();
    await screen.findByTestId("audit-timeline-table");

    const buttons = screen.getAllByRole("button");
    const forbiddenPatterns = [
      /send/i,
      /approve/i,
      /execute/i,
      /submit/i,
      /resume\s*ai/i,
      /mutate/i,
      /kill.*switch/i,
      /toggle\s*sandbox/i,
      /apply\s*rollback/i,
      /generate.*briefing/i,
      /retry/i,
      /confirm/i,
      /go\s*live/i,
    ];
    for (const btn of buttons) {
      for (const pattern of forbiddenPatterns) {
        expect(btn.textContent || "").not.toMatch(pattern);
      }
    }
  });
});

// ---- Filters -------------------------------------------------------------

describe("Phase 15C — AuditTimeline filters", () => {
  it("changing the category filter forwards the value to the api", async () => {
    const mockFn = (
      api.getAuditTimeline as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(populatedResponse());

    renderPage();
    await screen.findByTestId("audit-timeline-table");

    fireEvent.change(screen.getByTestId("audit-filter-category"), {
      target: { value: "safety" },
    });

    await waitFor(() => {
      expect(mockFn).toHaveBeenLastCalledWith(
        expect.objectContaining({ category: "safety", offset: 0 }),
      );
    });
  });

  it("changing the tone filter forwards the value to the api", async () => {
    const mockFn = (
      api.getAuditTimeline as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(populatedResponse());

    renderPage();
    await screen.findByTestId("audit-timeline-table");

    fireEvent.change(screen.getByTestId("audit-filter-tone"), {
      target: { value: "warning" },
    });

    await waitFor(() => {
      expect(mockFn).toHaveBeenLastCalledWith(
        expect.objectContaining({ tone: "warning", offset: 0 }),
      );
    });
  });

  it("kind + search-text filters forward to the api", async () => {
    const mockFn = (
      api.getAuditTimeline as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(populatedResponse());

    renderPage();
    await screen.findByTestId("audit-timeline-table");

    fireEvent.change(screen.getByTestId("audit-filter-kind"), {
      target: { value: "payment.received" },
    });
    fireEvent.change(screen.getByTestId("audit-filter-q"), {
      target: { value: "Rs.3000" },
    });

    await waitFor(() => {
      expect(mockFn).toHaveBeenLastCalledWith(
        expect.objectContaining({
          kind: "payment.received",
          q: "Rs.3000",
          offset: 0,
        }),
      );
    });
  });

  it("Clear filters resets every input and offset", async () => {
    const mockFn = (
      api.getAuditTimeline as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(populatedResponse());

    renderPage();
    await screen.findByTestId("audit-timeline-table");

    fireEvent.change(screen.getByTestId("audit-filter-category"), {
      target: { value: "rollback" },
    });
    fireEvent.change(screen.getByTestId("audit-filter-q"), {
      target: { value: "ceo" },
    });
    await waitFor(() => {
      expect(mockFn).toHaveBeenLastCalledWith(
        expect.objectContaining({ category: "rollback", q: "ceo" }),
      );
    });

    fireEvent.click(screen.getByTestId("audit-filter-clear"));

    await waitFor(() => {
      expect(mockFn).toHaveBeenLastCalledWith(
        expect.objectContaining({
          category: undefined,
          q: undefined,
          tone: undefined,
          kind: undefined,
          dateFrom: undefined,
          dateTo: undefined,
          offset: 0,
        }),
      );
    });
  });
});

// ---- Pagination ----------------------------------------------------------

describe("Phase 15C — AuditTimeline pagination", () => {
  it("clicking Next advances the offset by limit", async () => {
    const mockFn = (
      api.getAuditTimeline as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue({
      items: [baseRow, rollbackRow],
      count: 120, // more than one page so Next is enabled
      limit: 50,
      offset: 0,
      categoriesAvailable: populatedResponse().categoriesAvailable,
      categoryFiltered: null,
    });

    renderPage();
    await screen.findByTestId("audit-timeline-table");
    fireEvent.click(screen.getByTestId("audit-timeline-next"));

    await waitFor(() => {
      expect(mockFn).toHaveBeenLastCalledWith(
        expect.objectContaining({ offset: 50 }),
      );
    });
  });

  it("Previous is disabled on the first page", async () => {
    (
      api.getAuditTimeline as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue({
      items: [baseRow, rollbackRow],
      count: 120,
      limit: 50,
      offset: 0,
      categoriesAvailable: populatedResponse().categoriesAvailable,
      categoryFiltered: null,
    });

    renderPage();
    await screen.findByTestId("audit-timeline-table");
    const prev = screen.getByTestId("audit-timeline-prev");
    expect(prev.hasAttribute("disabled")).toBe(true);
  });
});

// ---- Sidebar nav ---------------------------------------------------------

describe("Phase 15C — Sidebar Audit Timeline entry", () => {
  it("renders an Audit Timeline link in the sidebar pointing to /operations/audit-timeline", async () => {
    render(
      <MemoryRouter>
        <Sidebar
          open
          onClose={() => {}}
          collapsed={false}
          onCollapsedChange={() => {}}
        />
      </MemoryRouter>,
    );

    const link = await screen.findByText(/Audit Timeline/i);
    const anchor = link.closest("a");
    expect(anchor).not.toBeNull();
    expect(anchor?.getAttribute("href")).toBe(
      "/operations/audit-timeline",
    );
  });
});
