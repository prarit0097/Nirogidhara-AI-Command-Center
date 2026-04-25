import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "@/App";
import Leads from "@/pages/Leads";
import Orders from "@/pages/Orders";
import { api } from "@/services/api";

describe("Nirogidhara frontend", () => {
  it("renders the app shell and sidebar navigation", () => {
    render(<App />);

    expect(screen.getByText("Nirogidhara")).toBeInTheDocument();
    expect(screen.getByText("Leads CRM")).toBeInTheDocument();
    expect(screen.getByText("Orders Pipeline")).toBeInTheDocument();
  });

  it("returns dashboard metrics through the API service", async () => {
    const metrics = await api.getDashboardMetrics();

    expect(metrics.leadsToday.value).toBeGreaterThan(0);
    expect(metrics.netProfit.value).toBeGreaterThan(0);
  });

  it("renders dashboard KPI cards", async () => {
    render(<App />);

    expect(await screen.findByText("Net Delivered Profit · 7d")).toBeInTheDocument();
    expect(screen.getByText("Lead to order workflow")).toBeInTheDocument();
  });

  it("renders the leads page with CRM rows", async () => {
    render(<Leads />);

    expect(screen.getByText("Leads CRM")).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText("Call").length).toBeGreaterThan(0));
  });

  it("renders the orders pipeline kanban", async () => {
    render(<Orders />);

    expect(screen.getByText("Orders Pipeline")).toBeInTheDocument();
    expect(await screen.findByText("New Lead")).toBeInTheDocument();
    expect(screen.getByText("Confirmation Pending")).toBeInTheDocument();
  });
});
