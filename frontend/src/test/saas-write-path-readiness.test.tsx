import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "@/App";
import { api } from "@/services/api";

describe("Phase 6D — Write-Path Readiness", () => {
  it("exposes the write-path-readiness API method", async () => {
    expect(typeof api.getSaasWritePathReadiness).toBe("function");

    const readiness = await api.getSaasWritePathReadiness();
    expect(readiness.writeContextHelpersAvailable).toBe(true);
    expect(readiness.auditAutoOrgContextEnabled).toBe(true);
    expect(readiness.globalTenantFilteringEnabled).toBe(false);
    expect(readiness.safeCreatePathsCovered.length).toBeGreaterThan(0);
    expect(readiness.modelsWithOrgBranch.length).toBeGreaterThan(0);

    const blob = JSON.stringify(readiness).toLowerCase();
    for (const needle of ["secret", "token", "password", "api_key", "+919"]) {
      expect(blob).not.toContain(needle);
    }
  });

  it("renders the write-path readiness card with no mutation buttons", async () => {
    render(<App />);

    await waitFor(() =>
      expect(screen.getByText("Write-path readiness")).toBeInTheDocument(),
    );
    expect(screen.getByText("Auto-assign signal")).toBeInTheDocument();
    expect(screen.getByText("Covered create paths")).toBeInTheDocument();
    expect(screen.getByText(/Deferred \(Phase 6E\)/)).toBeInTheDocument();
    // Read-only — no run-backfill / run-migrate / org-switch buttons.
    expect(
      screen.queryByRole("button", { name: /Run backfill/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Run migrate/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Switch organization/i }),
    ).not.toBeInTheDocument();
  });
});
