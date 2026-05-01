import { render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import WhatsAppMonitoringPage from "@/pages/WhatsAppMonitoring";

function renderWithRouter(node: React.ReactNode) {
  return render(<BrowserRouter>{node}</BrowserRouter>);
}

describe("WhatsApp Monitoring page", () => {
  it("renders the dashboard header and gate status cards from mock data", async () => {
    renderWithRouter(<WhatsAppMonitoringPage />);

    expect(
      screen.getByText("WhatsApp Auto-Reply Monitoring"),
    ).toBeInTheDocument();
    // Gate status cards land after the API mock falls through.
    await waitFor(() =>
      expect(screen.getByText("Gate status")).toBeInTheDocument(),
    );
    expect(screen.getByText("Provider")).toBeInTheDocument();
    expect(screen.getByText("Limited test mode")).toBeInTheDocument();
    expect(screen.getByText("Auto-reply enabled")).toBeInTheDocument();
    expect(screen.getByText("Allowed list size")).toBeInTheDocument();
  });

  it("shows activity metrics and mutation safety section", async () => {
    renderWithRouter(<WhatsAppMonitoringPage />);

    await waitFor(() =>
      expect(
        screen.getByText(/^Activity \(last/),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("Auto replies sent")).toBeInTheDocument();
    expect(screen.getByText("Deterministic builder")).toBeInTheDocument();
    expect(
      screen.getByText("Unexpected non-allowed sends"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByText(/Mutation safety/),
      ).toBeInTheDocument(),
    );
    // Clean state — green confirmation message.
    expect(
      screen.getByText(/All clean — auto-reply path mutated nothing/),
    ).toBeInTheDocument();
  });

  it("shows approved customer pilot readiness without send controls", async () => {
    renderWithRouter(<WhatsAppMonitoringPage />);

    await waitFor(() =>
      expect(
        screen.getByText("Approved Customer Pilot Readiness"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("Pilot members")).toBeInTheDocument();
    expect(screen.getByText("Consent missing")).toBeInTheDocument();
    expect(
      screen.getByText("verify_customer_consent_before_pilot"),
    ).toBeInTheDocument();
    expect(screen.getByText("+91*****99011")).toBeInTheDocument();
    expect(screen.queryByText("+919000099011")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Pilot|Approve|Pause|Send/i }),
    ).not.toBeInTheDocument();
  });

  it("renders the cohort table with masked numbers only", async () => {
    renderWithRouter(<WhatsAppMonitoringPage />);

    await waitFor(() =>
      expect(screen.getByText(/^Internal cohort/)).toBeInTheDocument(),
    );
    // Masked phone is present.
    expect(screen.getByText("+91*****99001")).toBeInTheDocument();
    // No full E.164 anywhere on the page.
    expect(screen.queryByText("+918949879990")).not.toBeInTheDocument();
  });

  it("renders the broad-automation flag pills as OFF/locked", async () => {
    renderWithRouter(<WhatsAppMonitoringPage />);

    await waitFor(() =>
      expect(
        screen.getByText(/Broad automation flags/),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("Call handoff: OFF / locked")).toBeInTheDocument();
    expect(screen.getByText("Lifecycle: OFF / locked")).toBeInTheDocument();
    expect(
      screen.getByText("Rescue discount: OFF / locked"),
    ).toBeInTheDocument();
    expect(screen.getByText("RTO rescue: OFF / locked")).toBeInTheDocument();
    expect(screen.getByText("Reorder Day-20: OFF / locked")).toBeInTheDocument();
    expect(screen.getByText("Campaigns: OFF / locked")).toBeInTheDocument();
  });

  it("renders refresh control and not enable/disable actions", async () => {
    renderWithRouter(<WhatsAppMonitoringPage />);

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /Refresh/ }),
      ).toBeInTheDocument(),
    );
    // Read-only — no enable/disable/send buttons.
    expect(
      screen.queryByRole("button", { name: /Enable/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Disable/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Send/ }),
    ).not.toBeInTheDocument();
  });

  it("shows the backend nextAction hint as a read-only string", async () => {
    renderWithRouter(<WhatsAppMonitoringPage />);

    await waitFor(() =>
      expect(
        screen.getByText("Backend recommendation (read-only)"),
      ).toBeInTheDocument(),
    );
    // The mock fixture's nextAction value must surface verbatim.
    expect(
      screen.getByText("ready_to_enable_limited_auto_reply_flag"),
    ).toBeInTheDocument();
  });
});
