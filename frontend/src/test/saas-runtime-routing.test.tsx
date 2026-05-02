import { render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import SaasAdminPage from "@/pages/SaasAdmin";
import { api } from "@/services/api";

function renderWithRouter(node: React.ReactNode) {
  return render(<BrowserRouter>{node}</BrowserRouter>);
}

describe("Phase 6F — Runtime Integration Routing Preview", () => {
  it("exposes the runtime-routing-readiness API method", async () => {
    expect(typeof api.getSaasRuntimeRoutingReadiness).toBe("function");

    const readiness = await api.getSaasRuntimeRoutingReadiness();
    expect(readiness.runtimeUsesPerOrgSettings).toBe(false);
    expect(readiness.perOrgRuntimeEnabled).toBe(false);
    expect(readiness.providers.length).toBeGreaterThan(0);
    for (const provider of readiness.providers) {
      expect(provider.runtimeSource).toBe("env_config");
      expect(provider.perOrgRuntimeEnabled).toBe(false);
    }
    // Mock fixture must never carry raw values.
    const blob = JSON.stringify(readiness).toLowerCase();
    for (const needle of ["password", "raw_secret", "secret_value"]) {
      expect(blob).not.toContain(needle);
    }
  });

  it("renders the Runtime Integration Routing Preview section on /saas-admin", async () => {
    renderWithRouter(<SaasAdminPage />);

    await waitFor(() =>
      expect(
        screen.getByText("Runtime Integration Routing Preview"),
      ).toBeInTheDocument(),
    );
    // Backend-derived header copy must surface verbatim.
    expect(
      screen.getByText(/Per-org runtime routing is not active\./),
    ).toBeInTheDocument();
    expect(screen.getByText("Env/config (active)")).toBeInTheDocument();
    expect(screen.getByText("false (Phase 6F)")).toBeInTheDocument();
    // Each of the six provider rows is rendered (the same six provider
    // names also appear in the Integration Readiness table; use the
    // testid-anchored row count to avoid the ambiguous text query).
    const rows = screen.getAllByTestId("runtime-provider-row");
    expect(rows.length).toBeGreaterThanOrEqual(6);
    expect(screen.getAllByText("WhatsApp Meta").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Razorpay").length).toBeGreaterThan(0);
    expect(screen.getAllByText("PayU").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Delhivery").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Vapi").length).toBeGreaterThan(0);
    expect(screen.getAllByText("OpenAI").length).toBeGreaterThan(0);
  });

  it("shows no activation/send/campaign buttons in the routing preview", async () => {
    renderWithRouter(<SaasAdminPage />);

    await waitFor(() =>
      expect(
        screen.getByText("Runtime Integration Routing Preview"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("button", { name: /Activate/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Enable runtime/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Send/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Start campaign/i }),
    ).not.toBeInTheDocument();
  });
});
