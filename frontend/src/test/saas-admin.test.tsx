import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import SaasAdminPage from "@/pages/SaasAdmin";
import { api } from "@/services/api";

describe("Phase 6E - SaaS Admin Panel", () => {
  it("exposes SaaS admin API client methods", async () => {
    expect(typeof api.getSaasAdminOverview).toBe("function");
    expect(typeof api.getSaasAdminOrganizations).toBe("function");
    expect(typeof api.getSaasIntegrationSettings).toBe("function");
    expect(typeof api.getSaasIntegrationReadiness).toBe("function");

    const overview = await api.getSaasAdminOverview();
    expect(overview.runtimeUsesPerOrgSettings).toBe(false);
    expect(overview.integrationReadiness.providers.length).toBeGreaterThan(0);
  });

  it("renders SaaS admin readiness sections without unsafe actions", async () => {
    render(<SaasAdminPage />);

    expect(await screen.findByText("SaaS Admin Panel")).toBeInTheDocument();
    expect(screen.getByText("Organization Overview")).toBeInTheDocument();
    expect(screen.getByText("Write Path Readiness")).toBeInTheDocument();
    expect(screen.getByText("Integration Readiness")).toBeInTheDocument();
    expect(screen.getByText("Safety Locks")).toBeInTheDocument();

    await waitFor(() =>
      expect(
        screen.getAllByText("WhatsApp Meta").length,
      ).toBeGreaterThan(0),
    );

    const body = document.body.textContent ?? "";
    expect(body).not.toContain("OPENAI_API_KEY");
    expect(body).not.toContain("META_WA_ACCESS_TOKEN");
    expect(body).not.toContain("+91");

    expect(
      screen.queryByRole("button", { name: /send/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /enable/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /campaign/i }),
    ).not.toBeInTheDocument();
  });
});

describe("Phase 6G - Controlled Runtime Routing Dry Run", () => {
  it("exposes Phase 6G API client methods with locked invariants", async () => {
    expect(typeof api.getSaasRuntimeDryRun).toBe("function");
    expect(typeof api.getSaasAiProviderRouting).toBe("function");
    expect(typeof api.getSaasControlledRuntimeReadiness).toBe("function");

    const report = await api.getSaasRuntimeDryRun();
    expect(report.dryRun).toBe(true);
    expect(report.liveExecutionAllowed).toBe(false);
    expect(report.runtimeSource).toBe("env_config");
    expect(report.perOrgRuntimeEnabled).toBe(false);
    expect(report.operations.length).toBe(14);
    for (const op of report.operations) {
      expect(op.dryRun).toBe(true);
      expect(op.liveExecutionAllowed).toBe(false);
      expect(op.externalCallWillBeMade).toBe(false);
      expect(op.runtimeSource).toBe("env_config");
      expect(op.perOrgRuntimeEnabled).toBe(false);
    }

    const ai = await api.getSaasAiProviderRouting();
    expect(ai.dryRun).toBe(true);
    expect(ai.liveCallWillBeMade).toBe(false);
    expect(ai.tasks.length).toBe(6);
    expect(ai.runtime.primaryProvider).toBe("nvidia");
    for (const task of ai.tasks) {
      expect(task.primaryProvider).toBe("nvidia");
      expect(task.dryRun).toBe(true);
      expect(task.liveCallWillBeMade).toBe(false);
      expect(task.maxTokens).toBeGreaterThan(0);
    }

    const readiness = await api.getSaasControlledRuntimeReadiness();
    expect(readiness.runtimeSource).toBe("env_config");
    expect(readiness.perOrgRuntimeEnabled).toBe(false);
    expect(readiness.operationCount).toBe(14);
    expect(readiness.aiTaskCount).toBe(6);
  });

  it("renders Phase 6G dry-run + AI provider sections without unsafe actions", async () => {
    render(<SaasAdminPage />);

    expect(
      await screen.findByText("Controlled Runtime Routing Dry Run"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("AI Provider Routing Preview"),
    ).toBeInTheDocument();

    const operationRows = await screen.findAllByTestId(
      "runtime-operation-row",
    );
    expect(operationRows.length).toBe(14);

    const aiTaskRows = await screen.findAllByTestId("ai-task-row");
    expect(aiTaskRows.length).toBe(6);

    // Per-task NVIDIA primary models render in the table.
    const body = document.body.textContent ?? "";
    expect(body).toContain("minimaxai/minimax-m2.7");
    expect(body).toContain("moonshotai/kimi-k2.6");
    expect(body).toContain("mistralai/mistral-medium-3.5-128b");
    expect(body).toContain("google/gemma-4-31b-it");

    // No SEND / RUN / ENABLE / EXECUTE buttons are rendered anywhere.
    expect(
      screen.queryByRole("button", { name: /run live/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /execute/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /go live/i }),
    ).not.toBeInTheDocument();

    // Customer-facing AI routes flag safety wrappers.
    expect(body).toContain("Wrappers required");
  });
});
