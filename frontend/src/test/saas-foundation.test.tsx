import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "@/App";
import { api } from "@/services/api";

describe("Phase 6A — SaaS Foundation", () => {
  it("renders the dashboard with the org badge in the topbar", async () => {
    render(<App />);

    // The badge falls through to the deterministic mock when the API
    // is offline (test runtime). The org name must surface verbatim.
    await waitFor(() =>
      expect(
        screen.getByText("Nirogidhara Private Limited"),
      ).toBeInTheDocument(),
    );
    // Read-only badge — no switching/enable/pause controls anywhere.
    expect(
      screen.queryByRole("button", { name: /Switch organization/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Pause organization/i }),
    ).not.toBeInTheDocument();
  });

  it("exposes the SaaS API methods on the api client", async () => {
    expect(typeof api.getSaasCurrentOrganization).toBe("function");
    expect(typeof api.getSaasMyOrganizations).toBe("function");
    expect(typeof api.getSaasFeatureFlags).toBe("function");

    const current = await api.getSaasCurrentOrganization();
    expect(current.organization?.code).toBe("nirogidhara");
    expect(current.organization?.name).toBe("Nirogidhara Private Limited");
    expect(current.organization?.defaultBranch?.code).toBe("main");
    // Sensitive settings never appear via the public API client.
    const blob = JSON.stringify(current).toLowerCase();
    for (const needle of ["secret", "token", "password", "api_key"]) {
      expect(blob).not.toContain(needle);
    }
  });

  it("returns the user's orgs and feature flags via the api client", async () => {
    const my = await api.getSaasMyOrganizations();
    expect(my.count).toBeGreaterThan(0);
    expect(my.organizations[0]?.code).toBe("nirogidhara");

    const flags = await api.getSaasFeatureFlags();
    expect(flags.organization?.code).toBe("nirogidhara");
    // Feature flag map is an object (possibly empty in mock).
    expect(typeof flags.featureFlags).toBe("object");
  });
});
