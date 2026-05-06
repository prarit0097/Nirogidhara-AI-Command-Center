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

describe("Phase 6M - Razorpay Webhook Handler (test-mode)", () => {
  it("exposes Phase 6M api methods returning safe shapes", async () => {
    expect(typeof api.getSaasRazorpayWebhookHandlerReadiness).toBe("function");
    expect(typeof api.getSaasRazorpayWebhookEvents).toBe("function");
    expect(typeof api.simulateSaasRazorpayWebhookEvent).toBe("function");

    const readiness = await api.getSaasRazorpayWebhookHandlerReadiness();
    expect(readiness.businessMutationEnabled).toBe(false);
    expect(readiness.customerNotificationEnabled).toBe(false);
    expect(readiness.businessMutationCount).toBe(0);
    expect(readiness.customerNotificationCount).toBe(0);
    expect(readiness.rawSecretExposureCount).toBe(0);
    expect(readiness.fullPiiExposureCount).toBe(0);

    const events = await api.getSaasRazorpayWebhookEvents();
    expect(events.businessMutationWasMade).toBe(false);
    expect(events.customerNotificationSent).toBe(false);
    expect(events.providerCallAttempted).toBe(false);
  });

  it("renders the Razorpay Webhook Handler section without payment buttons", async () => {
    render(<SaasAdminPage />);
    expect(
      await screen.findByText("Razorpay Webhook Handler (Test Mode)"),
    ).toBeInTheDocument();
    const section = await screen.findByTestId(
      "razorpay-webhook-handler-section",
    );
    expect(section).toBeInTheDocument();
    expect(section.textContent).toContain("Handler readiness");
    expect(section.textContent).toContain("Counters (must stay 0)");

    // No live payment / capture / notify buttons.
    expect(
      screen.queryByRole("button", { name: /capture payment/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /mark order paid/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /replay event/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /send whatsapp/i }),
    ).not.toBeInTheDocument();

    const body = document.body.textContent ?? "";
    expect(body).not.toContain("phase6m_FAKEsecret");
  });
});

describe("Phase 6M-0 - MCP Gateway Foundation", () => {
  it("exposes MCP api methods that return safe-default shapes", async () => {
    expect(typeof api.getMcpReadiness).toBe("function");
    expect(typeof api.getMcpSecurityPosture).toBe("function");
    expect(typeof api.getMcpTools).toBe("function");
    expect(typeof api.getMcpResources).toBe("function");
    expect(typeof api.getMcpPrompts).toBe("function");
    expect(typeof api.getMcpInvocations).toBe("function");
    expect(typeof api.simulateMcpToolCall).toBe("function");

    const readiness = await api.getMcpReadiness();
    expect(readiness.mcpEnabled).toBe(false);
    expect(readiness.readOnlyMode).toBe(true);
    expect(readiness.writeToolsEnabled).toBe(false);
    expect(readiness.providerToolsEnabled).toBe(false);
    expect(readiness.providerCallAttemptedCount).toBe(0);
    expect(readiness.businessMutationAttemptedCount).toBe(0);

    const posture = await api.getMcpSecurityPosture();
    expect(posture.safe).toBe(true);
    expect(posture.forbiddenToolsRegistered).toBe(false);
    expect(posture.writeToolsEnabled).toBe(false);
    expect(posture.providerToolsEnabled).toBe(false);

    const tools = await api.getMcpTools();
    expect(tools.readOnlyMode).toBe(true);
    expect(tools.writeToolsEnabled).toBe(false);
    expect(tools.providerToolsEnabled).toBe(false);
    for (const tool of tools.tools) {
      expect(tool.readOnly).toBe(true);
      expect(tool.providerCallAllowed).toBe(false);
      expect(tool.businessMutationAllowed).toBe(false);
    }

    const sim = await api.simulateMcpToolCall("system.get_phase_status");
    expect(sim.providerCallAttempted).toBe(false);
    expect(sim.businessMutationAttempted).toBe(false);
  });

  it("renders the MCP Gateway Readiness section without execute buttons", async () => {
    render(<SaasAdminPage />);
    expect(
      await screen.findByText("MCP Gateway Readiness"),
    ).toBeInTheDocument();
    const section = await screen.findByTestId("mcp-gateway-section");
    expect(section).toBeInTheDocument();
    expect(section.textContent).toContain("Security posture");

    const toolRows = await screen.findAllByTestId("mcp-tool-row");
    expect(toolRows.length).toBeGreaterThan(0);

    // No execute / send / run-live buttons.
    expect(
      screen.queryByRole("button", { name: /run tool live/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /execute mcp/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /send/i }),
    ).not.toBeInTheDocument();

    // Document body must not carry sample raw secrets.
    const body = document.body.textContent ?? "";
    expect(body).not.toContain("rzp_test_FAKE");
    expect(body).not.toContain("sk_test_");
    expect(body).not.toContain("sk-ant-");
  });
});

describe("Phase 6L - Razorpay Audit Review + Webhook Readiness", () => {
  it("exposes Phase 6L API methods returning safe shapes", async () => {
    expect(typeof api.getSaasRazorpayExecutionAudit).toBe("function");
    expect(typeof api.getSaasRazorpayWebhookReadiness).toBe("function");
    expect(typeof api.getSaasRazorpayWebhookPlan).toBe("function");

    const audit = await api.getSaasRazorpayExecutionAudit("pex_demo");
    expect(audit.passed).toBe(true);
    expect(audit.rollbackStatus).toBe("completed");
    expect(audit.rawSecretLeakDetected).toBe(false);

    const readiness = await api.getSaasRazorpayWebhookReadiness();
    expect(readiness.razorpayWebhookSecretPresent).toBe(true);
    expect(readiness.isTestKey).toBe(true);
    expect(readiness.isLiveKey).toBe(false);
    expect(readiness.safeToPlanWebhookReadiness).toBe(true);

    const plan = await api.getSaasRazorpayWebhookPlan();
    expect(plan.phase).toBe("6L");
    expect(plan.endpointDesign.phase6LRegistration).toBe(false);
    expect(plan.signatureVerificationDesign.algorithm).toBe("HMAC-SHA256");
    expect(plan.replayProtection.windowSeconds).toBe(300);
    expect(plan.eventAllowlist.length).toBeGreaterThan(0);
    expect(plan.eventDenylist.length).toBeGreaterThan(0);
    for (const value of Object.values(plan.businessMutationPolicy)) {
      expect(value).toBe(false);
    }
  });

  it("renders the Razorpay audit + webhook section without execute buttons", async () => {
    render(<SaasAdminPage />);
    expect(
      await screen.findByText(
        "Razorpay Test Execution Audit + Webhook Readiness",
      ),
    ).toBeInTheDocument();
    const section = await screen.findByTestId(
      "razorpay-audit-webhook-section",
    );
    expect(section).toBeInTheDocument();

    // Allow/deny lists render.
    const allowRows = await screen.findAllByTestId(
      "razorpay-webhook-allowlist-row",
    );
    expect(allowRows.length).toBeGreaterThan(0);
    const denyRows = await screen.findAllByTestId(
      "razorpay-webhook-denylist-row",
    );
    expect(denyRows.length).toBeGreaterThan(0);

    // Section text contains the Phase 6L scope copy.
    expect(section.textContent).toContain("HMAC-SHA256");
    expect(section.textContent).toContain("Phase 6K execution audit");

    // No execute / register-webhook / capture buttons.
    expect(
      screen.queryByRole("button", { name: /execute razorpay/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /register webhook/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /capture/i }),
    ).not.toBeInTheDocument();

    // Document body must not carry the test-fixture raw key.
    const body = document.body.textContent ?? "";
    expect(body).not.toContain("rzp_test_FAKEphase6l");
    expect(body).not.toContain("rzp_live_");
  });
});

describe("Phase 6K - Single Internal Razorpay Test-Mode Execution Gate", () => {
  it("exposes Phase 6K API client methods with locked invariants", async () => {
    expect(typeof api.getSaasProviderExecutionAttempts).toBe("function");
    expect(typeof api.getSaasProviderExecutionAttempt).toBe("function");
    expect(typeof api.prepareSaasProviderExecutionAttempt).toBe("function");
    expect(typeof api.rollbackSaasProviderExecutionAttempt).toBe("function");
    expect(typeof api.archiveSaasProviderExecutionAttempt).toBe("function");

    const report = await api.getSaasProviderExecutionAttempts();
    expect(report.runtimeSource).toBe("env_config");
    expect(report.perOrgRuntimeEnabled).toBe(false);
    expect(report.businessMutationCount).toBe(0);
    expect(report.providerCallAttemptedCount).toBe(0);
    expect(report.externalCallMadeCount).toBe(0);
    expect(report.policy?.allowedInPhase6K).toBe(true);
    expect(report.policy?.amountPaise).toBe(100);
    expect(report.policy?.currency).toBe("INR");
    expect(report.policy?.apiExecutionAllowed).toBe(false);
    expect(report.policy?.frontendExecutionAllowed).toBe(false);
    expect(report.policy?.maxExecutionsPerApprovedPlan).toBe(1);
  });

  it("renders Razorpay execution gate section without execute buttons", async () => {
    render(<SaasAdminPage />);
    expect(
      await screen.findByText(
        "Single Internal Razorpay Test-Mode Execution Gate",
      ),
    ).toBeInTheDocument();
    const section = await screen.findByTestId(
      "provider-execution-gate-section",
    );
    expect(section).toBeInTheDocument();
    expect(section.textContent).toContain("Razorpay execution-gate env");

    // No execute / create-order / capture / send buttons.
    expect(
      screen.queryByRole("button", { name: /execute razorpay/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /create order/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /capture/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /go live/i }),
    ).not.toBeInTheDocument();

    const body = document.body.textContent ?? "";
    // Raw test-mode key sample (used by tests only) must never appear.
    expect(body).not.toContain("rzp_test_FAKEphase6k");
    expect(body).not.toContain("rzp_live_");
  });
});

describe("Phase 6J - Single Internal Provider Test Plan", () => {
  it("exposes Phase 6J API client methods with locked invariants", async () => {
    expect(typeof api.getSaasProviderTestPlans).toBe("function");
    expect(typeof api.prepareSaasProviderTestPlan).toBe("function");
    expect(typeof api.validateSaasProviderTestPlan).toBe("function");
    expect(typeof api.approveSaasProviderTestPlan).toBe("function");
    expect(typeof api.rejectSaasProviderTestPlan).toBe("function");
    expect(typeof api.archiveSaasProviderTestPlan).toBe("function");

    const report = await api.getSaasProviderTestPlans();
    expect(report.dryRun).toBe(true);
    expect(report.providerCallAllowed).toBe(false);
    expect(report.externalCallWillBeMade).toBe(false);
    expect(report.externalCallWasMade).toBe(false);
    expect(report.providerCallAttempted).toBe(false);
    expect(report.runtimeSource).toBe("env_config");
    expect(report.perOrgRuntimeEnabled).toBe(false);
    expect(report.phase6jImplementationTargets).toEqual([
      "razorpay.create_order",
    ]);
    if (report.latestPlan) {
      expect(report.latestPlan.realMoney).toBe(false);
      expect(report.latestPlan.realCustomerDataAllowed).toBe(false);
      expect(report.latestPlan.providerCallAllowed).toBe(false);
      expect(report.latestPlan.dryRun).toBe(true);
    }
  });

  it("renders Single Internal Provider Test Plan section without execute buttons", async () => {
    render(<SaasAdminPage />);
    expect(
      await screen.findByText("Single Internal Provider Test Plan"),
    ).toBeInTheDocument();
    const section = await screen.findByTestId("provider-test-plan-section");
    expect(section).toBeInTheDocument();

    // Safety invariants are rendered.
    expect(section.textContent).toContain("Safety invariants");
    expect(section.textContent).toContain("Razorpay env readiness");
    expect(section.textContent).toContain("razorpay.create_order");

    // No execute / create / live buttons exist.
    expect(
      screen.queryByRole("button", { name: /execute/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /create order/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /create payment link/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /go live/i }),
    ).not.toBeInTheDocument();

    // No raw secret values in the document body.
    const body = document.body.textContent ?? "";
    expect(body).not.toContain("rzp_test_FAKE");
    expect(body).not.toContain("rzp_live_");
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

describe("Phase 6N - Razorpay Business Mutation Sandbox Plan", () => {
  it("exposes the Phase 6N planning API methods on the api client", async () => {
    expect(
      typeof api.getSaasRazorpayBusinessMutationSandboxPlan,
    ).toBe("function");
    expect(
      typeof api.getSaasRazorpayBusinessMutationSandboxReadiness,
    ).toBe("function");

    const plan = await api.getSaasRazorpayBusinessMutationSandboxPlan();
    expect(plan.phase).toBe("6N");
    expect(plan.status).toBe("planning_only");
    expect(plan.businessMutationEnabled).toBe(false);
    expect(plan.customerNotificationEnabled).toBe(false);
    expect(plan.rawPayloadStorageEnabled).toBe(false);
    expect(plan.eventMappings.length).toBe(9);
    plan.eventMappings.forEach((row) => {
      expect(row.mutationAllowedInPhase6N).toBe(false);
      expect(row.customerNotificationAllowed).toBe(false);
      expect(row.shipmentEffectAllowed).toBe(false);
      expect(row.discountEffectAllowed).toBe(false);
    });

    const readiness =
      await api.getSaasRazorpayBusinessMutationSandboxReadiness();
    expect(readiness.phase).toBe("6N");
    expect(readiness.businessMutationEnabled).toBe(false);
    expect(readiness.customerNotificationEnabled).toBe(false);
    expect(readiness.rawPayloadStorageEnabled).toBe(false);
  });

  it("renders the Phase 6N section with locked safety state and no forbidden buttons", async () => {
    render(<SaasAdminPage />);

    expect(
      await screen.findByText("Razorpay Business Mutation Sandbox Plan"),
    ).toBeInTheDocument();

    await waitFor(() => {
      expect(
        screen.getByTestId("phase6n-event-mapping-table"),
      ).toBeInTheDocument();
    });

    expect(
      screen.getByTestId("phase6n-manual-review-list"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("phase6n-rollback-list"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("phase6n-forbidden-actions"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("phase6n-safe-to-start-phase6o-badge"),
    ).toBeInTheDocument();

    // Mutation locks rendered as "Disabled" — multiple times across the
    // metric grid + the per-event mapping rows.
    expect(screen.getAllByText(/Disabled/i).length).toBeGreaterThan(5);

    // No forbidden Phase 6N buttons exist anywhere on the page.
    const forbiddenButtonPatterns = [
      /mark paid/i,
      /capture payment/i,
      /refund/i,
      /create payment link/i,
      /mutate order/i,
      /execute webhook/i,
      /replay event/i,
      /enable mutation/i,
      /go live/i,
      /run mcp tool/i,
    ];
    for (const pattern of forbiddenButtonPatterns) {
      expect(
        screen.queryByRole("button", { name: pattern }),
      ).not.toBeInTheDocument();
    }

    // No raw secret values + no full Indian phone numbers leak through.
    const body = document.body.textContent ?? "";
    expect(body).not.toContain("rzp_live_");
    expect(body).not.toContain("RAZORPAY_KEY_SECRET");
    expect(body).not.toContain("RAZORPAY_WEBHOOK_SECRET=");
    expect(body).not.toMatch(/\+91\d{10}/);
  });
});

describe("Phase 6O - Razorpay Sandbox Status Mapping + Manual Review", () => {
  it("exposes the Phase 6O API methods on the api client", async () => {
    expect(
      typeof api.getSaasRazorpaySandboxStatusMappingReadiness,
    ).toBe("function");
    expect(
      typeof api.getSaasRazorpaySandboxStatusReviews,
    ).toBe("function");
    expect(
      typeof api.prepareSaasRazorpaySandboxStatusReview,
    ).toBe("function");
    expect(
      typeof api.approveSaasRazorpaySandboxStatusReview,
    ).toBe("function");
    expect(
      typeof api.rejectSaasRazorpaySandboxStatusReview,
    ).toBe("function");
    expect(
      typeof api.archiveSaasRazorpaySandboxStatusReview,
    ).toBe("function");

    const readiness = await api.getSaasRazorpaySandboxStatusMappingReadiness();
    expect(readiness.phase).toBe("6O");
    expect(readiness.status).toBe("sandbox_review_only");
    expect(readiness.businessMutationEnabled).toBe(false);
    expect(readiness.customerNotificationEnabled).toBe(false);
    expect(readiness.providerCallAttempted).toBe(false);
    expect(readiness.razorpaySandboxStatusMappingEnabled).toBe(false);
    expect(readiness.eventMappings.length).toBe(9);
    readiness.eventMappings.forEach((row) => {
      expect(row.mutationAllowedInPhase6O).toBe(false);
      expect(row.customerNotificationAllowed).toBe(false);
      expect(row.shipmentEffectAllowed).toBe(false);
      expect(row.discountEffectAllowed).toBe(false);
    });

    const reviews = await api.getSaasRazorpaySandboxStatusReviews();
    expect(reviews.phase).toBe("6O");
    expect(reviews.businessMutationWasMade).toBe(false);
    expect(reviews.customerNotificationSent).toBe(false);
    expect(reviews.providerCallAttempted).toBe(false);
  });

  it("renders the Phase 6O section with locked safety state and review-only labels", async () => {
    render(<SaasAdminPage />);

    expect(
      await screen.findByText(
        "Razorpay Sandbox Status Mapping + Manual Review",
      ),
    ).toBeInTheDocument();

    await waitFor(() => {
      expect(
        screen.getByTestId("phase6o-event-mapping-table"),
      ).toBeInTheDocument();
    });

    expect(
      screen.getByTestId("phase6o-manual-review-list"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("phase6o-forbidden-actions"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("phase6o-safe-to-start-phase6p-badge"),
    ).toBeInTheDocument();

    // Locks rendered as "Disabled" multiple times across the metric
    // grid + per-event mapping rows.
    expect(screen.getAllByText(/Disabled/i).length).toBeGreaterThan(5);

    // Forbidden Phase 6O / 6P buttons are absent.
    const forbiddenButtonPatterns = [
      /^mark paid$/i,
      /^capture payment$/i,
      /^refund$/i,
      /^create payment link$/i,
      /^mutate order$/i,
      /^execute webhook$/i,
      /^replay event$/i,
      /^enable mutation$/i,
      /^go live$/i,
      /^run mcp tool$/i,
      /^apply mutation$/i,
      /^execute payment$/i,
    ];
    for (const pattern of forbiddenButtonPatterns) {
      expect(
        screen.queryByRole("button", { name: pattern }),
      ).not.toBeInTheDocument();
    }

    // No raw secret / env-var names / full phone leak.
    const body = document.body.textContent ?? "";
    expect(body).not.toContain("rzp_live_");
    expect(body).not.toContain("RAZORPAY_KEY_SECRET");
    expect(body).not.toContain("RAZORPAY_WEBHOOK_SECRET=");
    expect(body).not.toMatch(/\+91\d{10}/);

    // Sandbox-review-only banner mentions "Sandbox review only".
    expect(
      screen.getAllByText(/Sandbox review only/i).length,
    ).toBeGreaterThan(0);
  });
});

describe("Phase 6P - Razorpay Sandbox Paid-Status Mutation Test", () => {
  it("exposes the Phase 6P API methods on the api client", async () => {
    expect(
      typeof api.getSaasRazorpaySandboxPaidStatusMutationReadiness,
    ).toBe("function");
    expect(
      typeof api.getSaasRazorpaySandboxPaidStatusMutationAttempts,
    ).toBe("function");

    const readiness =
      await api.getSaasRazorpaySandboxPaidStatusMutationReadiness();
    expect(readiness.phase).toBe("6P");
    expect(readiness.status).toBe("sandbox_ledger_only");
    expect(readiness.razorpaySandboxPaidStatusMutationEnabled).toBe(false);
    expect(readiness.frontendCanExecute).toBe(false);
    expect(readiness.apiEndpointCanExecute).toBe(false);
    expect(readiness.executionPath).toBe("cli_only");
    expect(readiness.eventMappings.length).toBe(9);
    readiness.eventMappings.forEach((row) => {
      expect(row.realOrderMutationAllowedInPhase6P).toBe(false);
      expect(row.realPaymentMutationAllowedInPhase6P).toBe(false);
      expect(row.customerNotificationAllowed).toBe(false);
      expect(row.providerCallAllowed).toBe(false);
      expect(row.shipmentEffectAllowed).toBe(false);
      expect(row.discountEffectAllowed).toBe(false);
    });

    const attempts =
      await api.getSaasRazorpaySandboxPaidStatusMutationAttempts();
    expect(attempts.phase).toBe("6P");
    expect(attempts.frontendCanExecute).toBe(false);
    expect(attempts.apiEndpointCanExecute).toBe(false);
    expect(attempts.realOrderMutationWasMade).toBe(false);
    expect(attempts.realPaymentMutationWasMade).toBe(false);
  });

  it("renders the Phase 6P section with locked safety state and CLI-only reminder", async () => {
    render(<SaasAdminPage />);

    expect(
      await screen.findByText("Razorpay Sandbox Paid-Status Mutation Test"),
    ).toBeInTheDocument();

    await waitFor(() => {
      expect(
        screen.getByTestId("phase6p-event-mapping-table"),
      ).toBeInTheDocument();
    });

    expect(
      screen.getByTestId("phase6p-cli-list"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("phase6p-forbidden-actions"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("phase6p-safe-to-start-phase6q-badge"),
    ).toBeInTheDocument();

    // Locks rendered as "Disabled" multiple times across the metric
    // grid + per-event mapping rows.
    expect(screen.getAllByText(/Disabled/i).length).toBeGreaterThan(8);

    // Forbidden Phase 6P / 6Q buttons are absent.
    const forbiddenButtonPatterns = [
      /^mark paid$/i,
      /^capture payment$/i,
      /^refund$/i,
      /^create payment link$/i,
      /^mutate order$/i,
      /^execute webhook$/i,
      /^replay event$/i,
      /^enable mutation$/i,
      /^go live$/i,
      /^run mcp tool$/i,
      /^apply mutation$/i,
      /^apply payment$/i,
      /^execute payment$/i,
      // Phase 6P specifically rules out frontend execute / rollback.
      /^execute sandbox/i,
      /^rollback sandbox/i,
    ];
    for (const pattern of forbiddenButtonPatterns) {
      expect(
        screen.queryByRole("button", { name: pattern }),
      ).not.toBeInTheDocument();
    }

    // No raw secret / env-var names / full phone leak.
    const body = document.body.textContent ?? "";
    expect(body).not.toContain("rzp_live_");
    expect(body).not.toContain("RAZORPAY_KEY_SECRET");
    expect(body).not.toContain("RAZORPAY_WEBHOOK_SECRET=");
    expect(body).not.toMatch(/\+91\d{10}/);

    // CLI-only reminder is present.
    expect(
      screen.getAllByText(/CLI-only/i).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText(/Sandbox ledger only/i).length,
    ).toBeGreaterThan(0);
  });
});

describe("Phase 6Q - Razorpay Payment → Order Workflow Safety Gate", () => {
  it("exposes the Phase 6Q API methods on the api client", async () => {
    expect(
      typeof api.getSaasRazorpayPaymentOrderWorkflowGateReadiness,
    ).toBe("function");
    expect(
      typeof api.getSaasRazorpayPaymentOrderWorkflowGates,
    ).toBe("function");

    const readiness =
      await api.getSaasRazorpayPaymentOrderWorkflowGateReadiness();
    expect(readiness.phase).toBe("6Q");
    expect(readiness.status).toBe("audit_gate_only");
    expect(readiness.razorpayPaymentOrderWorkflowGateEnabled).toBe(false);
    expect(readiness.frontendCanExecute).toBe(false);
    expect(readiness.apiEndpointCanExecute).toBe(false);
    expect(readiness.apiEndpointCanApprove).toBe(false);
    expect(readiness.executionPath).toBe("cli_only");
    expect(readiness.workflowContract.length).toBe(9);
    readiness.workflowContract.forEach((row) => {
      expect(row.workflowMutationAllowedInPhase6Q).toBe(false);
      expect(row.customerNotificationAllowed).toBe(false);
      expect(row.providerCallAllowed).toBe(false);
      expect(row.shipmentEffectAllowed).toBe(false);
      expect(row.discountEffectAllowed).toBe(false);
    });

    const gates = await api.getSaasRazorpayPaymentOrderWorkflowGates();
    expect(gates.phase).toBe("6Q");
    expect(gates.frontendCanExecute).toBe(false);
    expect(gates.apiEndpointCanExecute).toBe(false);
    expect(gates.apiEndpointCanApprove).toBe(false);
    expect(gates.realOrderMutationWasMade).toBe(false);
    expect(gates.realPaymentMutationWasMade).toBe(false);
  });

  it("renders the Phase 6Q section with locked safety state and CLI-only reminder", async () => {
    render(<SaasAdminPage />);

    expect(
      await screen.findByText(
        "Razorpay Payment → Order Workflow Safety Gate",
      ),
    ).toBeInTheDocument();

    await waitFor(() => {
      expect(
        screen.getByTestId("phase6q-contract-table"),
      ).toBeInTheDocument();
    });

    expect(screen.getByTestId("phase6q-cli-list")).toBeInTheDocument();
    expect(
      screen.getByTestId("phase6q-forbidden-actions"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("phase6q-safe-to-start-phase6r-badge"),
    ).toBeInTheDocument();

    // Locks rendered as "Disabled" multiple times.
    expect(screen.getAllByText(/Disabled/i).length).toBeGreaterThan(8);

    // Forbidden Phase 6Q / 6R buttons absent.
    const forbiddenButtonPatterns = [
      /^mark paid$/i,
      /^capture payment$/i,
      /^refund$/i,
      /^create payment link$/i,
      /^mutate order$/i,
      /^execute webhook$/i,
      /^replay event$/i,
      /^enable mutation$/i,
      /^go live$/i,
      /^run mcp tool$/i,
      /^apply mutation$/i,
      /^apply payment$/i,
      /^execute payment$/i,
      /^execute workflow$/i,
      /^apply order update$/i,
      /^confirm paid order$/i,
      /^start live workflow$/i,
      /^approve gate$/i,
      /^reject gate$/i,
    ];
    for (const pattern of forbiddenButtonPatterns) {
      expect(
        screen.queryByRole("button", { name: pattern }),
      ).not.toBeInTheDocument();
    }

    // No raw secret / env-var names / full phone leak.
    const body = document.body.textContent ?? "";
    expect(body).not.toContain("rzp_live_");
    expect(body).not.toContain("RAZORPAY_KEY_SECRET");
    expect(body).not.toContain("RAZORPAY_WEBHOOK_SECRET=");
    expect(body).not.toMatch(/\+91\d{10}/);

    // CLI-only + audit-gate-only banners present.
    expect(
      screen.getAllByText(/CLI-only/i).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText(/Audit gate only/i).length,
    ).toBeGreaterThan(0);
  });
});

describe("Phase 6R - Razorpay Payment → WhatsApp / Courier Dispatch Readiness", () => {
  it("exposes the Phase 6R API methods on the api client", async () => {
    expect(
      typeof api.getSaasRazorpayPaymentDispatchReadiness,
    ).toBe("function");
    expect(
      typeof api.getSaasRazorpayPaymentDispatchReadinessGates,
    ).toBe("function");

    const readiness = await api.getSaasRazorpayPaymentDispatchReadiness();
    expect(readiness.phase).toBe("6R");
    expect(readiness.status).toBe("dispatch_readiness_only");
    expect(readiness.latestCompletedPhase).toBe("6Q");
    expect(readiness.nextPhase).toBe("6S");
    expect(readiness.razorpayPaymentDispatchReadinessEnabled).toBe(false);
    expect(readiness.frontendCanExecute).toBe(false);
    expect(readiness.apiEndpointCanExecute).toBe(false);
    expect(readiness.apiEndpointCanApprove).toBe(false);
    expect(readiness.executionPath).toBe("cli_only");
    expect(readiness.maxSafeAmountPaise).toBe(100);
    expect(readiness.readinessContract.length).toBe(9);
    readiness.readinessContract.forEach((row) => {
      expect(row.whatsappSendAllowedInPhase6R).toBe(false);
      expect(row.courierBookingAllowedInPhase6R).toBe(false);
      expect(row.providerCallAllowedInPhase6R).toBe(false);
      expect(row.customerNotificationAllowed).toBe(false);
      expect(row.shipmentEffectAllowed).toBe(false);
      expect(row.discountEffectAllowed).toBe(false);
    });
    expect(readiness.safetyInvariants.whatsappSendAllowed).toBe(false);
    expect(readiness.safetyInvariants.delhiveryCallAllowed).toBe(false);
    expect(readiness.safetyInvariants.razorpayApiInvocationAllowed).toBe(
      false,
    );

    const gates = await api.getSaasRazorpayPaymentDispatchReadinessGates();
    expect(gates.phase).toBe("6R");
    expect(gates.frontendCanExecute).toBe(false);
    expect(gates.apiEndpointCanExecute).toBe(false);
    expect(gates.apiEndpointCanApprove).toBe(false);
    expect(gates.realOrderMutationWasMade).toBe(false);
    expect(gates.realPaymentMutationWasMade).toBe(false);
    expect(gates.shipmentCreated).toBe(false);
    expect(gates.whatsAppMessageCreated).toBe(false);
    expect(gates.whatsAppMessageQueued).toBe(false);
    expect(gates.metaCloudCallAttempted).toBe(false);
    expect(gates.delhiveryCallAttempted).toBe(false);
  });

  it("renders the Phase 6R section with locked safety state and CLI-only reminder", async () => {
    render(<SaasAdminPage />);

    expect(
      await screen.findByText(
        "Razorpay Payment → WhatsApp / Courier Dispatch Readiness",
      ),
    ).toBeInTheDocument();

    await waitFor(() => {
      expect(
        screen.getByTestId("razorpay-payment-dispatch-readiness-section"),
      ).toBeInTheDocument();
    });

    expect(
      screen.getByTestId("phase6r-safe-to-start-phase6s-badge"),
    ).toBeInTheDocument();

    // Locks rendered as "Disabled" multiple times.
    expect(screen.getAllByText(/Disabled/i).length).toBeGreaterThan(8);

    // Forbidden Phase 6R buttons absent.
    const forbiddenButtonPatterns = [
      /^send whatsapp$/i,
      /^queue whatsapp$/i,
      /^create shipment$/i,
      /^create awb$/i,
      /^book courier$/i,
      /^dispatch order$/i,
      /^notify customer$/i,
      /^mark paid$/i,
      /^capture payment$/i,
      /^refund$/i,
      /^apply mutation$/i,
      /^mutate order$/i,
      /^create payment link$/i,
      /^execute webhook$/i,
      /^replay event$/i,
      /^enable mutation$/i,
      /^go live$/i,
      /^run mcp tool$/i,
      /^execute workflow$/i,
      /^apply order update$/i,
      /^confirm paid order$/i,
      /^start live workflow$/i,
      /^approve readiness$/i,
      /^reject readiness$/i,
    ];
    for (const pattern of forbiddenButtonPatterns) {
      expect(
        screen.queryByRole("button", { name: pattern }),
      ).not.toBeInTheDocument();
    }

    // No raw secret / env-var names / full phone leak.
    const body = document.body.textContent ?? "";
    expect(body).not.toContain("rzp_live_");
    expect(body).not.toContain("RAZORPAY_KEY_SECRET");
    expect(body).not.toContain("RAZORPAY_WEBHOOK_SECRET=");
    expect(body).not.toMatch(/\+91\d{10}/);

    // Readiness-only banner present.
    expect(
      screen.getAllByText(/Readiness contract only/i).length,
    ).toBeGreaterThan(0);
  });
});
