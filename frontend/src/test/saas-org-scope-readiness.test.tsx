import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "@/App";
import { api } from "@/services/api";

describe("Phase 6C — Org-Scope Readiness", () => {
  it("exposes the org-scope-readiness API method", async () => {
    expect(typeof api.getSaasOrgScopeReadiness).toBe("function");

    const readiness = await api.getSaasOrgScopeReadiness();
    expect(readiness.defaultOrganizationCode).toBe("nirogidhara");
    expect(readiness.auditAutoOrgContextEnabled).toBe(true);
    expect(readiness.globalTenantFilteringEnabled).toBe(false);
    expect(typeof readiness.organizationCoveragePercent).toBe("number");
    expect(Array.isArray(readiness.scopedModels)).toBe(true);

    const blob = JSON.stringify(readiness).toLowerCase();
    for (const needle of ["secret", "token", "password", "api_key"]) {
      expect(blob).not.toContain(needle);
    }
  });

  it("renders the org-scope readiness card on the dashboard with no mutation buttons", async () => {
    render(<App />);

    await waitFor(() =>
      expect(screen.getByText("Org-scope readiness")).toBeInTheDocument(),
      { timeout: 5000 },
    );
    // Backend-derived header copy must surface verbatim. Multiple
    // Phase 6 cards share the "Off (Phase 6E)" label, so use the
    // *AllBy* variant.
    expect(screen.getAllByText("Off (Phase 6E)").length).toBeGreaterThan(
      0,
    );
    // Read-only — no mutation/switch buttons.
    expect(
      screen.queryByRole("button", { name: /Switch organization/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Enable global filter/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Run backfill/i }),
    ).not.toBeInTheDocument();
  });
});
