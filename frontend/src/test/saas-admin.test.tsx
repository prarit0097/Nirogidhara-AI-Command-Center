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

describe("Phase 6H - Controlled Runtime Live Audit Gate", () => {
  it("exposes Phase 6H API client methods with no-execution invariants", async () => {
    expect(typeof api.getSaasRuntimeLiveGate).toBe("function");
    expect(typeof api.getSaasRuntimeLiveGateRequests).toBe("function");
    expect(typeof api.getSaasRuntimeLiveGatePolicies).toBe("function");
    expect(typeof api.getSaasRuntimeLiveGateKillSwitch).toBe("function");
    expect(typeof api.previewSaasRuntimeLiveGate).toBe("function");

    const gate = await api.getSaasRuntimeLiveGate();
    expect(gate.runtimeSource).toBe("env_config");
    expect(gate.perOrgRuntimeEnabled).toBe(false);
    expect(gate.defaultDryRun).toBe(true);
    expect(gate.liveExecutionAllowed).toBe(false);
    expect(gate.externalCallWillBeMade).toBe(false);
    expect(gate.killSwitch.globalEnabled).toBe(true);
    expect(gate.operationPolicies.length).toBe(13);

    const preview = await api.previewSaasRuntimeLiveGate({
      operationType: "whatsapp.send_text",
    });
    expect(preview.dryRun).toBe(true);
    expect(preview.liveExecutionAllowed).toBe(false);
    expect(preview.externalCallWillBeMade).toBe(false);
  });

  it("renders live audit gate section without provider execution buttons or secrets", async () => {
    render(<SaasAdminPage />);

    expect(
      await screen.findByText("Controlled Runtime Live Audit Gate"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Approving in Phase 6H does not execute external calls."),
    ).toBeInTheDocument();
    expect(screen.getByText(/Global kill switch enabled/i)).toBeInTheDocument();
    expect(screen.getByText("Approval Queue")).toBeInTheDocument();

    const rows = await screen.findAllByTestId("live-gate-policy-row");
    expect(rows.length).toBe(13);

    const body = document.body.textContent ?? "";
    expect(body).toContain("whatsapp.send_text");
    expect(body).toContain("razorpay.create_order");
    expect(body).toContain("PayU deferred.");
    expect(body).not.toContain("META_WA_ACCESS_TOKEN");
    expect(body).not.toContain("RAZORPAY_KEY_SECRET");
    expect(body).not.toContain("+91 9");

    expect(
      screen.queryByRole("button", { name: /send whatsapp/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /create payment/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /create shipment/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /place call/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /execute/i }),
    ).not.toBeInTheDocument();
  });
});

describe("Phase 6I - Single Internal Live Gate Simulation", () => {
  it("exposes Phase 6I API client methods with no-provider-call invariants", async () => {
    expect(typeof api.getSaasRuntimeLiveGateSimulations).toBe("function");
    expect(typeof api.prepareSaasRuntimeLiveGateSimulation).toBe("function");
    expect(typeof api.requestSaasRuntimeLiveGateSimulationApproval).toBe(
      "function",
    );
    expect(typeof api.approveSaasRuntimeLiveGateSimulation).toBe("function");
    expect(typeof api.rejectSaasRuntimeLiveGateSimulation).toBe("function");
    expect(typeof api.runSaasRuntimeLiveGateSimulation).toBe("function");
    expect(typeof api.rollbackSaasRuntimeLiveGateSimulation).toBe("function");

    const simulations = await api.getSaasRuntimeLiveGateSimulations();
    expect(simulations.defaultOperation).toBe("razorpay.create_order");
    expect(simulations.allowedOperations).toEqual([
      "razorpay.create_order",
      "whatsapp.send_text",
      "ai.smoke_test",
    ]);
    expect(simulations.dryRun).toBe(true);
    expect(simulations.liveExecutionAllowed).toBe(false);
    expect(simulations.externalCallWillBeMade).toBe(false);
    expect(simulations.externalCallWasMade).toBe(false);
    expect(simulations.providerCallAttempted).toBe(false);
    expect(simulations.killSwitchActive).toBe(true);
  });

  it("renders Phase 6I simulation section without provider execution controls", async () => {
    render(<SaasAdminPage />);

    expect(
      await screen.findByText("Single Internal Live Gate Simulation"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Approving or running a Phase 6I simulation/i),
    ).toBeInTheDocument();

    const rows = await screen.findAllByTestId("live-gate-simulation-row");
    expect(rows.length).toBeGreaterThan(0);

    const body = document.body.textContent ?? "";
    expect(body).toContain("razorpay.create_order");
    expect(body).toContain("ai.smoke_test");
    expect(body).not.toContain("RAZORPAY_KEY_SECRET");
    expect(body).not.toContain("META_WA_ACCESS_TOKEN");
    expect(body).not.toContain("+91 9");

    expect(
      screen.queryByRole("button", { name: /send whatsapp/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /create razorpay/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /run provider/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /execute/i }),
    ).not.toBeInTheDocument();
  });
});
