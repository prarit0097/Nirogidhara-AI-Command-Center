import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

// Preserve real isApiError / ApiError; replace only the `api` object so the
// pages render without a backend.
vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return {
    ...actual,
    api: {
      getImportsOverview: vi.fn(),
      getImportDatasets: vi.fn(),
      getImportCampaigns: vi.fn(),
      getImportCampaignQueue: vi.fn(),
    },
  };
});

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

import DataImports from "@/pages/DataImports";
import ImportedCampaigns from "@/pages/ImportedCampaigns";
import { api } from "@/services/api";

const here = dirname(fileURLToPath(import.meta.url));
const APP_SRC = readFileSync(resolve(here, "../App.tsx"), "utf8");

beforeEach(() => {
  vi.clearAllMocks();
  (api.getImportsOverview as any).mockResolvedValue(null);
  (api.getImportDatasets as any).mockResolvedValue({ items: [], total: 0 });
  (api.getImportCampaigns as any).mockResolvedValue({ items: [], total: 0 });
  (api.getImportCampaignQueue as any).mockResolvedValue({ items: [], total: 0 });
});

describe("Phase 16D-Hotfix-1 — route aliases registered in App.tsx", () => {
  // Regression guard for the exact bug: /operations/imported-campaigns was
  // missing (only /operations/import-campaigns shipped in b74b737).
  it("registers the canonical operations routes", () => {
    expect(APP_SRC).toContain('path="/operations/data-imports"');
    expect(APP_SRC).toContain('path="/operations/imported-campaigns"');
  });

  it("keeps the back-compat import-campaigns alias", () => {
    expect(APP_SRC).toContain('path="/operations/import-campaigns"');
  });

  it("registers the top-level aliases", () => {
    expect(APP_SRC).toContain('path="/data-imports"');
    expect(APP_SRC).toContain('path="/imported-campaigns"');
  });

  it("wires both routes to the correct page components", () => {
    // data-imports → DataImportsPage, imported-campaigns → ImportedCampaignsPage
    expect(APP_SRC).toMatch(
      /path="\/operations\/data-imports"\s*\n\s*element=\{<DataImportsPage \/>\}/,
    );
    expect(APP_SRC).toMatch(
      /path="\/operations\/imported-campaigns"\s*\n\s*element=\{<ImportedCampaignsPage \/>\}/,
    );
  });
});

describe("Phase 16D-Hotfix-1 — pages render at their canonical routes", () => {
  const renderAt = (path: string) =>
    render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/operations/data-imports" element={<DataImports />} />
          <Route
            path="/operations/imported-campaigns"
            element={<ImportedCampaigns />}
          />
        </Routes>
      </MemoryRouter>,
    );

  it("renders Data Imports at /operations/data-imports", async () => {
    renderAt("/operations/data-imports");
    expect(await screen.findByTestId("data-imports-page")).toBeInTheDocument();
  });

  it("renders Imported Campaigns at /operations/imported-campaigns", async () => {
    renderAt("/operations/imported-campaigns");
    expect(
      await screen.findByTestId("imported-campaigns-page"),
    ).toBeInTheDocument();
  });
});

describe("Phase 16D-Hotfix-1 — sidebar links use canonical operations paths", () => {
  const SIDEBAR_SRC = readFileSync(
    resolve(here, "../components/layout/Sidebar.tsx"),
    "utf8",
  );

  it("Data Imports nav points to /operations/data-imports", () => {
    expect(SIDEBAR_SRC).toContain('to: "/operations/data-imports"');
  });

  it("Imported Campaigns nav points to /operations/imported-campaigns", () => {
    expect(SIDEBAR_SRC).toContain('to: "/operations/imported-campaigns"');
  });
});
