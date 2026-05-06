import { useEffect, useState, type ReactNode } from "react";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill, toneForStatus } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { api } from "@/services/api";
import type {
  SaasAdminOverview,
  SaasAiProviderRoutePreview,
  SaasAiProviderRoutingPreview,
  SaasProviderReadiness,
  SaasProviderExecutionAttempt,
  SaasProviderExecutionReadiness,
  SaasProviderTestPlan,
  SaasProviderTestPlanReadiness,
  McpGatewayReadiness,
  McpInvocationsResponse,
  McpSecurityPosture,
  McpToolDefinitionDto,
  McpToolInvocationDto,
  McpToolsResponse,
  SaasRazorpayAuditReview,
  SaasRazorpayWebhookEventDto,
  SaasRazorpayBusinessMutationSandboxPlan,
  SaasRazorpayBusinessMutationSandboxReadiness,
  SaasRazorpayPaymentDispatchPilotPlanReadiness,
  SaasRazorpayPaymentDispatchPilotPlansResponse,
  SaasRazorpayPaymentDispatchReadiness,
  SaasRazorpayPaymentDispatchReadinessGatesResponse,
  SaasRazorpayPhase6FinalAuditLockReadiness,
  SaasRazorpayPhase6FinalAuditLocksResponse,
  SaasRazorpayPaymentOrderWorkflowGateReadiness,
  SaasRazorpayPaymentOrderWorkflowGatesResponse,
  SaasRazorpaySandboxPaidStatusMutationAttemptsResponse,
  SaasRazorpaySandboxPaidStatusMutationReadiness,
  SaasRazorpaySandboxStatusMappingReadiness,
  SaasRazorpaySandboxStatusReviewDto,
  SaasRazorpaySandboxStatusReviewsResponse,
  SaasRazorpayWebhookEventsResponse,
  SaasRazorpayWebhookHandlerReadiness,
  SaasRazorpayWebhookPlan,
  SaasRazorpayWebhookReadiness,
  SaasRuntimeLiveGateSummary,
  SaasLiveGatePolicy,
  SaasRuntimeDryRunOperationDecision,
  SaasRuntimeDryRunReport,
  SaasRuntimeLiveGateSimulation,
  SaasRuntimeLiveGateSimulationsResponse,
  SaasRuntimeRoutingProviderPreview,
  SaasRuntimeRoutingReadiness,
} from "@/types/domain";
import {
  Building2,
  CheckCircle2,
  Cpu,
  AlertTriangle,
  Bot,
  ClipboardList,
  CreditCard,
  FileSearch,
  KeyRound,
  Network,
  Webhook,
  LockKeyhole,
  PlayCircle,
  RefreshCw,
  ShieldCheck,
  ShieldAlert,
  SlidersHorizontal,
  Workflow,
  type LucideIcon,
} from "lucide-react";

function boolTone(
  value: boolean,
  successWhenTrue = true,
): "success" | "danger" {
  return value === successWhenTrue ? "success" : "danger";
}

export default function SaasAdminPage() {
  const [overview, setOverview] = useState<SaasAdminOverview | null>(null);
  const [routing, setRouting] =
    useState<SaasRuntimeRoutingReadiness | null>(null);
  const [dryRun, setDryRun] = useState<SaasRuntimeDryRunReport | null>(null);
  const [aiRouting, setAiRouting] =
    useState<SaasAiProviderRoutingPreview | null>(null);
  const [liveGate, setLiveGate] =
    useState<SaasRuntimeLiveGateSummary | null>(null);
  const [simulations, setSimulations] =
    useState<SaasRuntimeLiveGateSimulationsResponse | null>(null);
  const [providerTestPlans, setProviderTestPlans] =
    useState<SaasProviderTestPlanReadiness | null>(null);
  const [providerExecutionGate, setProviderExecutionGate] =
    useState<SaasProviderExecutionReadiness | null>(null);
  const [razorpayWebhookReadiness, setRazorpayWebhookReadiness] =
    useState<SaasRazorpayWebhookReadiness | null>(null);
  const [razorpayWebhookPlan, setRazorpayWebhookPlan] =
    useState<SaasRazorpayWebhookPlan | null>(null);
  const [razorpayAuditReview, setRazorpayAuditReview] =
    useState<SaasRazorpayAuditReview | null>(null);
  const [mcpReadiness, setMcpReadiness] =
    useState<McpGatewayReadiness | null>(null);
  const [mcpSecurityPosture, setMcpSecurityPosture] =
    useState<McpSecurityPosture | null>(null);
  const [mcpTools, setMcpTools] = useState<McpToolsResponse | null>(null);
  const [mcpInvocations, setMcpInvocations] =
    useState<McpInvocationsResponse | null>(null);
  const [razorpayWebhookHandlerReadiness, setRazorpayWebhookHandlerReadiness] =
    useState<SaasRazorpayWebhookHandlerReadiness | null>(null);
  const [razorpayWebhookEvents, setRazorpayWebhookEvents] =
    useState<SaasRazorpayWebhookEventsResponse | null>(null);
  const [
    razorpayBusinessMutationSandboxPlan,
    setRazorpayBusinessMutationSandboxPlan,
  ] = useState<SaasRazorpayBusinessMutationSandboxPlan | null>(null);
  const [
    razorpayBusinessMutationSandboxReadiness,
    setRazorpayBusinessMutationSandboxReadiness,
  ] = useState<SaasRazorpayBusinessMutationSandboxReadiness | null>(null);
  const [
    razorpaySandboxStatusMappingReadiness,
    setRazorpaySandboxStatusMappingReadiness,
  ] = useState<SaasRazorpaySandboxStatusMappingReadiness | null>(null);
  const [
    razorpaySandboxStatusReviews,
    setRazorpaySandboxStatusReviews,
  ] = useState<SaasRazorpaySandboxStatusReviewsResponse | null>(null);
  const [phase6oActionPending, setPhase6oActionPending] = useState<number | null>(
    null,
  );
  const [phase6oActionMessage, setPhase6oActionMessage] = useState<string>("");
  const [
    razorpaySandboxPaidStatusReadiness,
    setRazorpaySandboxPaidStatusReadiness,
  ] = useState<SaasRazorpaySandboxPaidStatusMutationReadiness | null>(null);
  const [
    razorpaySandboxPaidStatusAttempts,
    setRazorpaySandboxPaidStatusAttempts,
  ] = useState<SaasRazorpaySandboxPaidStatusMutationAttemptsResponse | null>(
    null,
  );
  const [
    razorpayPaymentOrderWorkflowReadiness,
    setRazorpayPaymentOrderWorkflowReadiness,
  ] = useState<SaasRazorpayPaymentOrderWorkflowGateReadiness | null>(null);
  const [
    razorpayPaymentOrderWorkflowGates,
    setRazorpayPaymentOrderWorkflowGates,
  ] = useState<SaasRazorpayPaymentOrderWorkflowGatesResponse | null>(null);
  const [
    razorpayPaymentDispatchReadiness,
    setRazorpayPaymentDispatchReadiness,
  ] = useState<SaasRazorpayPaymentDispatchReadiness | null>(null);
  const [
    razorpayPaymentDispatchReadinessGates,
    setRazorpayPaymentDispatchReadinessGates,
  ] = useState<SaasRazorpayPaymentDispatchReadinessGatesResponse | null>(null);
  const [
    razorpayPaymentDispatchPilotPlanReadiness,
    setRazorpayPaymentDispatchPilotPlanReadiness,
  ] = useState<SaasRazorpayPaymentDispatchPilotPlanReadiness | null>(null);
  const [
    razorpayPaymentDispatchPilotPlans,
    setRazorpayPaymentDispatchPilotPlans,
  ] = useState<SaasRazorpayPaymentDispatchPilotPlansResponse | null>(null);
  const [
    razorpayPhase6FinalAuditLockReadiness,
    setRazorpayPhase6FinalAuditLockReadiness,
  ] = useState<SaasRazorpayPhase6FinalAuditLockReadiness | null>(null);
  const [
    razorpayPhase6FinalAuditLocks,
    setRazorpayPhase6FinalAuditLocks,
  ] = useState<SaasRazorpayPhase6FinalAuditLocksResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    Promise.all([
      api.getSaasAdminOverview(),
      api.getSaasRuntimeRoutingReadiness(),
      api.getSaasRuntimeDryRun(),
      api.getSaasAiProviderRouting(),
      api.getSaasRuntimeLiveGate(),
      api.getSaasRuntimeLiveGateSimulations(),
      api.getSaasProviderTestPlans(),
      api.getSaasProviderExecutionAttempts(),
      api.getSaasRazorpayWebhookReadiness(),
      api.getSaasRazorpayWebhookPlan(),
      api.getMcpReadiness(),
      api.getMcpSecurityPosture(),
      api.getMcpTools(),
      api.getMcpInvocations(25),
      api.getSaasRazorpayWebhookHandlerReadiness(),
      api.getSaasRazorpayWebhookEvents(25),
      api.getSaasRazorpayBusinessMutationSandboxPlan(),
      api.getSaasRazorpayBusinessMutationSandboxReadiness(),
      api.getSaasRazorpaySandboxStatusMappingReadiness(),
      api.getSaasRazorpaySandboxStatusReviews(25),
      api.getSaasRazorpaySandboxPaidStatusMutationReadiness(),
      api.getSaasRazorpaySandboxPaidStatusMutationAttempts(25),
      api.getSaasRazorpayPaymentOrderWorkflowGateReadiness(),
      api.getSaasRazorpayPaymentOrderWorkflowGates(25),
      api.getSaasRazorpayPaymentDispatchReadiness(),
      api.getSaasRazorpayPaymentDispatchReadinessGates(25),
      api.getSaasRazorpayPaymentDispatchPilotPlanReadiness(),
      api.getSaasRazorpayPaymentDispatchPilotPlans(25),
      api.getSaasRazorpayPhase6FinalAuditLockReadiness(),
      api.getSaasRazorpayPhase6FinalAuditLocks(25),
    ])
      .then(
        ([
          ov,
          rt,
          dr,
          ai,
          gate,
          sims,
          ptp,
          exec,
          wbr,
          wbp,
          mcpR,
          mcpSp,
          mcpT,
          mcpInv,
          hr,
          wbe,
          bmPlan,
          bmRead,
          smRead,
          smReviews,
          spsRead,
          spsAttempts,
          poRead,
          poGates,
          pdRead,
          pdGates,
          ppRead,
          ppPlans,
          p6tRead,
          p6tLocks,
        ]) => {
          setOverview(ov);
          setRouting(rt);
          setDryRun(dr);
          setAiRouting(ai);
          setLiveGate(gate);
          setSimulations(sims);
          setProviderTestPlans(ptp);
          setProviderExecutionGate(exec);
          setRazorpayWebhookReadiness(wbr);
          setRazorpayWebhookPlan(wbp);
          setMcpReadiness(mcpR);
          setMcpSecurityPosture(mcpSp);
          setMcpTools(mcpT);
          setMcpInvocations(mcpInv);
          setRazorpayWebhookHandlerReadiness(hr);
          setRazorpayWebhookEvents(wbe);
          setRazorpayBusinessMutationSandboxPlan(bmPlan);
          setRazorpayBusinessMutationSandboxReadiness(bmRead);
          setRazorpaySandboxStatusMappingReadiness(smRead);
          setRazorpaySandboxStatusReviews(smReviews);
          setRazorpaySandboxPaidStatusReadiness(spsRead);
          setRazorpaySandboxPaidStatusAttempts(spsAttempts);
          setRazorpayPaymentOrderWorkflowReadiness(poRead);
          setRazorpayPaymentOrderWorkflowGates(poGates);
          setRazorpayPaymentDispatchReadiness(pdRead);
          setRazorpayPaymentDispatchReadinessGates(pdGates);
          setRazorpayPaymentDispatchPilotPlanReadiness(ppRead);
          setRazorpayPaymentDispatchPilotPlans(ppPlans);
          setRazorpayPhase6FinalAuditLockReadiness(p6tRead);
          setRazorpayPhase6FinalAuditLocks(p6tLocks);
          // Auto-load the audit review for the latest succeeded
          // execution if present.
          const latestSucceeded = wbr?.latestSucceededExecutionId;
          if (latestSucceeded) {
            api
              .getSaasRazorpayExecutionAudit(latestSucceeded)
              .then(setRazorpayAuditReview)
              .catch(() => setRazorpayAuditReview(null));
          } else {
            setRazorpayAuditReview(null);
          }
        },
      )
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  if (loading && overview === null) {
    return (
      <div className="grid h-96 place-items-center text-muted-foreground">
        Loading...
      </div>
    );
  }

  if (overview === null) {
    return (
      <div className="grid h-96 place-items-center text-muted-foreground">
        SaaS admin data unavailable.
      </div>
    );
  }

  const org = overview.organization;
  const writeReadiness = overview.writePathReadiness;
  const orgReadiness = overview.orgScopeReadiness;

  return (
    <>
      <PageHeader
        eyebrow="SaaS Control"
        title="SaaS Admin Panel"
        description="Read-only organization scope, write-path, integration readiness, and safety-lock visibility for the current single-tenant deployment."
        actions={
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
        }
      />

      <div className="grid gap-4 lg:grid-cols-4">
        <MetricCard
          icon={Building2}
          label="Active org"
          value={org?.code ?? "missing"}
          detail={org?.name ?? "Default organization not found"}
        />
        <MetricCard
          icon={ShieldCheck}
          label="Org coverage"
          value={`${orgReadiness.organizationCoveragePercent.toFixed(2)}%`}
          detail={`Branch ${orgReadiness.branchCoveragePercent.toFixed(2)}%`}
        />
        <MetricCard
          icon={Workflow}
          label="Write enforcement"
          value={writeReadiness.enforcementMode ?? "advisory"}
          detail={`${writeReadiness.recentRowsWithoutOrganizationLast24h} recent unscoped writes`}
        />
        <MetricCard
          icon={KeyRound}
          label="Integration settings"
          value={String(overview.integrationSettingsCount)}
          detail="Runtime still uses env/config"
        />
      </div>

      <section className="mt-6 grid gap-4 lg:grid-cols-2">
        <Panel title="Organization Overview" icon={Building2}>
          <KeyValue label="Organization" value={org?.name ?? "Missing"} />
          <KeyValue label="Code" value={org?.code ?? "missing"} />
          <KeyValue
            label="Default branch"
            value={org?.defaultBranch?.name ?? "Missing"}
          />
          <KeyValue
            label="Memberships"
            value={String(org?.membershipSummary.active ?? 0)}
          />
          <StatusPill tone={toneForStatus(org?.status ?? "missing")}>
            {org?.status ?? "missing"}
          </StatusPill>
        </Panel>

        <Panel title="Org Scope Readiness" icon={ShieldCheck}>
          <KeyValue
            label="Global tenant filtering"
            value={String(orgReadiness.globalTenantFilteringEnabled)}
          />
          <KeyValue
            label="Scoped models"
            value={String(orgReadiness.scopedModels.length)}
          />
          <KeyValue
            label="Unscoped APIs"
            value={String(orgReadiness.unscopedApis.length)}
          />
          <StatusPill
            tone={boolTone(orgReadiness.safeToStartPhase6D)}
          >
            {orgReadiness.safeToStartPhase6D
              ? "Ready"
              : "Needs attention"}
          </StatusPill>
        </Panel>
      </section>

      <section className="mt-6 grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <Panel title="Write Path Readiness" icon={Workflow}>
          <div className="grid gap-3 sm:grid-cols-3">
            <KeyValue
              label="Covered paths"
              value={String(
                writeReadiness.coveredSafeCreatePaths?.length ??
                  writeReadiness.safeCreatePathsCovered.length,
              )}
            />
            <KeyValue
              label="Deferred paths"
              value={String(writeReadiness.deferredCreatePaths.length)}
            />
            <KeyValue
              label="Recent unscoped"
              value={String(
                writeReadiness.recentUnscopedWritesLast24h ??
                  writeReadiness.recentRowsWithoutOrganizationLast24h,
              )}
            />
          </div>
          <div className="mt-4 rounded-md border border-border bg-muted/20 p-3 text-sm">
            <div className="text-xs uppercase text-muted-foreground">
              Next action
            </div>
            <div className="mt-1 font-medium">{writeReadiness.nextAction}</div>
          </div>
          <IssueList items={writeReadiness.blockers} empty="No blockers" />
        </Panel>

        <Panel title="Safety Locks" icon={LockKeyhole}>
          <LockRow
            label="WhatsApp auto-reply"
            safe={!overview.safetyLocks.whatsappAutoReplyEnabled}
          />
          <LockRow label="Campaigns" safe={overview.safetyLocks.campaignsLocked} />
          <LockRow label="Broadcast" safe={overview.safetyLocks.broadcastLocked} />
          <LockRow
            label="Lifecycle automation"
            safe={!overview.safetyLocks.lifecycleAutomationEnabled}
          />
          <LockRow
            label="Call handoff"
            safe={!overview.safetyLocks.callHandoffEnabled}
          />
          <LockRow
            label="Rescue / RTO / reorder"
            safe={
              !overview.safetyLocks.rescueDiscountEnabled &&
              !overview.safetyLocks.rtoRescueEnabled &&
              !overview.safetyLocks.reorderDay20Enabled
            }
          />
        </Panel>
      </section>

      <section className="mt-6 surface-card overflow-hidden">
        <div className="border-b border-border px-6 py-4">
          <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
            <SlidersHorizontal className="h-5 w-5 text-primary" />
            Integration Readiness
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="bg-muted/30 text-[11px] uppercase text-muted-foreground">
              <tr>
                <th className="px-6 py-3 text-left font-medium">Provider</th>
                <th className="py-3 text-left font-medium">Status</th>
                <th className="py-3 text-left font-medium">Secret refs</th>
                <th className="py-3 text-left font-medium">Validation</th>
                <th className="px-6 py-3 text-left font-medium">Runtime</th>
              </tr>
            </thead>
            <tbody>
              {overview.integrationReadiness.providers.map((provider) => (
                <ProviderRow key={provider.providerType} provider={provider} />
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {routing && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="runtime-routing-preview"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <SlidersHorizontal className="h-5 w-5 text-primary" />
                Runtime Integration Routing Preview
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6F preview only. Per-org runtime routing is not
                active — runtime still uses env/config. Secret refs are
                checked for presence only; raw values are never exposed.
              </p>
            </div>
            <StatusPill
              tone={routing.global.safeToStartPhase6G ? "success" : "warning"}
            >
              {routing.global.safeToStartPhase6G
                ? "Phase 6G ready"
                : "Phase 6G blocked"}
            </StatusPill>
          </div>
          <div className="grid gap-3 px-6 py-4 sm:grid-cols-3">
            <KeyValue
              label="Runtime source"
              value="Env/config (active)"
            />
            <KeyValue
              label="Per-org runtime enabled"
              value="false (Phase 6F)"
            />
            <KeyValue
              label="Next action"
              value={routing.nextAction}
            />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[800px] text-sm">
              <thead className="bg-muted/30 text-[11px] uppercase text-muted-foreground">
                <tr>
                  <th className="px-6 py-3 text-left font-medium">
                    Provider
                  </th>
                  <th className="py-3 text-left font-medium">Setting</th>
                  <th className="py-3 text-left font-medium">Status</th>
                  <th className="py-3 text-left font-medium">
                    Secret refs
                  </th>
                  <th className="py-3 text-left font-medium">
                    Resolvable
                  </th>
                  <th className="px-6 py-3 text-left font-medium">
                    Runtime source
                  </th>
                </tr>
              </thead>
              <tbody>
                {routing.providers.map((provider) => (
                  <RuntimeProviderRow
                    key={provider.providerType}
                    provider={provider}
                  />
                ))}
              </tbody>
            </table>
          </div>
          <div className="border-t border-border bg-warning/5 px-6 py-3 text-xs text-muted-foreground">
            Per-org runtime routing is not active. Runtime still uses
            env/config.
          </div>
        </section>
      )}

      {dryRun && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="runtime-dry-run-preview"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <PlayCircle className="h-5 w-5 text-primary" />
                Controlled Runtime Routing Dry Run
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6G preview only. No external provider calls, no
                customer-facing side effects. Runtime stays on env/config
                — per-org runtime routing is not active.
              </p>
            </div>
            <StatusPill
              tone={dryRun.global.safeToStartPhase6H ? "success" : "warning"}
            >
              {dryRun.global.safeToStartPhase6H
                ? "Phase 6H ready"
                : "Phase 6H blocked"}
            </StatusPill>
          </div>
          <div className="grid gap-3 px-6 py-4 sm:grid-cols-4">
            <KeyValue label="Operations" value={String(dryRun.operations.length)} />
            <KeyValue
              label="Live execution"
              value="false (Phase 6G)"
            />
            <KeyValue label="External call" value="false" />
            <KeyValue label="Next action" value={dryRun.nextAction} />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[920px] text-sm">
              <thead className="bg-muted/30 text-[11px] uppercase text-muted-foreground">
                <tr>
                  <th className="px-6 py-3 text-left font-medium">
                    Operation
                  </th>
                  <th className="py-3 text-left font-medium">Provider</th>
                  <th className="py-3 text-left font-medium">Risk</th>
                  <th className="py-3 text-left font-medium">Setting</th>
                  <th className="py-3 text-left font-medium">Dry-run</th>
                  <th className="py-3 text-left font-medium">Live</th>
                  <th className="px-6 py-3 text-left font-medium">
                    Next action
                  </th>
                </tr>
              </thead>
              <tbody>
                {dryRun.operations.map((op) => (
                  <RuntimeOperationRow
                    key={op.operationType}
                    decision={op}
                  />
                ))}
              </tbody>
            </table>
          </div>
          <div className="border-t border-border bg-warning/5 px-6 py-3 text-xs text-muted-foreground">
            Phase 6G is preview only. PayU + Delhivery are deferred until
            credentials are provisioned. Vapi awaits phone_number_id +
            webhook_secret.
          </div>
        </section>
      )}

      {aiRouting && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="ai-provider-routing"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <Cpu className="h-5 w-5 text-primary" />
                AI Provider Routing Preview
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                NVIDIA primary models with OpenAI / Anthropic fallback.
                Customer-facing drafts must still pass Claim Vault, safety
                stack, and approval matrix before any future live send.
              </p>
            </div>
            <StatusPill tone={aiRouting.safeToStartAiDryRun ? "success" : "warning"}>
              {aiRouting.runtime.runtimeMode === "preview"
                ? "Preview mode"
                : aiRouting.runtime.runtimeMode}
            </StatusPill>
          </div>
          <div className="grid gap-3 px-6 py-4 sm:grid-cols-4">
            <KeyValue
              label="Primary"
              value={aiRouting.runtime.primaryProvider}
            />
            <KeyValue
              label="Fallback"
              value={aiRouting.runtime.fallbackProvider}
            />
            <KeyValue
              label="NVIDIA key"
              value={
                aiRouting.runtime.envKeyPresence?.NVIDIA_API_KEY
                  ? "present"
                  : "missing"
              }
            />
            <KeyValue
              label="OpenAI fallback"
              value={
                aiRouting.runtime.envKeyPresence?.OPENAI_API_KEY
                  ? "present"
                  : "missing"
              }
            />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-sm">
              <thead className="bg-muted/30 text-[11px] uppercase text-muted-foreground">
                <tr>
                  <th className="px-6 py-3 text-left font-medium">Task</th>
                  <th className="py-3 text-left font-medium">Primary</th>
                  <th className="py-3 text-left font-medium">Fallback</th>
                  <th className="py-3 text-left font-medium">Max tokens</th>
                  <th className="py-3 text-left font-medium">Safety</th>
                  <th className="px-6 py-3 text-left font-medium">
                    Next action
                  </th>
                </tr>
              </thead>
              <tbody>
                {aiRouting.tasks.map((task) => (
                  <AiTaskRow key={task.taskType} task={task} />
                ))}
              </tbody>
            </table>
          </div>
          {aiRouting.blockers.length > 0 && (
            <div className="border-t border-border bg-warning/5 px-6 py-3 text-xs text-muted-foreground">
              {aiRouting.blockers.join(" · ")}
            </div>
          )}
        </section>
      )}

      {liveGate && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="runtime-live-gate"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldAlert className="h-5 w-5 text-primary" />
                Controlled Runtime Live Audit Gate
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Approving in Phase 6H does not execute external calls. The
                gate records readiness, approvals, blockers, and kill-switch
                state before any future provider-side execution.
              </p>
            </div>
            <StatusPill
              tone={liveGate.killSwitch.globalEnabled ? "success" : "warning"}
            >
              Global kill switch {liveGate.killSwitch.globalEnabled ? "enabled" : "disabled"}
            </StatusPill>
          </div>

          <div className="grid gap-3 px-6 py-4 sm:grid-cols-5">
            <KeyValue label="Runtime source" value={liveGate.runtimeSource} />
            <KeyValue
              label="Per-org runtime"
              value={String(liveGate.perOrgRuntimeEnabled)}
            />
            <KeyValue
              label="Default dry-run"
              value={String(liveGate.defaultDryRun)}
            />
            <KeyValue
              label="Live execution"
              value={String(liveGate.liveExecutionAllowed)}
            />
            <KeyValue
              label="External calls"
              value={String(liveGate.externalCallWillBeMade)}
            />
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[1080px] text-sm">
              <thead className="bg-muted/30 text-[11px] uppercase text-muted-foreground">
                <tr>
                  <th className="px-6 py-3 text-left font-medium">Operation</th>
                  <th className="py-3 text-left font-medium">Provider</th>
                  <th className="py-3 text-left font-medium">Risk</th>
                  <th className="py-3 text-left font-medium">Approval</th>
                  <th className="py-3 text-left font-medium">CAIO</th>
                  <th className="py-3 text-left font-medium">Consent</th>
                  <th className="py-3 text-left font-medium">Claim Vault</th>
                  <th className="py-3 text-left font-medium">Webhook</th>
                  <th className="py-3 text-left font-medium">Decision</th>
                  <th className="px-6 py-3 text-left font-medium">Live now</th>
                </tr>
              </thead>
              <tbody>
                {liveGate.operationPolicies.map((policy) => (
                  <LiveGatePolicyRow
                    key={policy.operationType}
                    policy={policy}
                  />
                ))}
              </tbody>
            </table>
          </div>

          <div className="grid gap-4 border-t border-border px-6 py-4 lg:grid-cols-[0.9fr_1.1fr]">
            <div className="space-y-3">
              <h4 className="flex items-center gap-2 font-display text-base font-semibold">
                <CheckCircle2 className="h-4 w-4 text-primary" />
                Approval Queue
              </h4>
              <KeyValue
                label="Pending"
                value={String(liveGate.approvalQueue.approvalPendingCount)}
              />
              <KeyValue
                label="Approved but not executed"
                value={String(liveGate.approvalQueue.approvedButNotExecutedCount)}
              />
              <KeyValue
                label="Rejected"
                value={String(liveGate.approvalQueue.rejectedCount)}
              />
              <KeyValue
                label="Blocked"
                value={String(liveGate.approvalQueue.blockedCount)}
              />
            </div>

            <div className="space-y-3">
              <h4 className="flex items-center gap-2 font-display text-base font-semibold">
                <ShieldCheck className="h-4 w-4 text-primary" />
                Recent Gate Audit Events
              </h4>
              {liveGate.recentGateAuditEvents.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No live gate audit events yet.
                </p>
              ) : (
                liveGate.recentGateAuditEvents.map((event) => (
                  <div
                    key={event.id}
                    className="rounded-md border border-border bg-muted/20 p-3"
                  >
                    <div className="text-sm font-medium">
                      {event.kind} - {event.operationType || "runtime"}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {event.gateDecision || "recorded"} -{" "}
                      {new Date(event.createdAt).toLocaleString()}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="border-t border-border bg-warning/5 px-6 py-4">
            <div className="flex items-center gap-2 text-sm font-medium text-warning">
              <AlertTriangle className="h-4 w-4" />
              Phase 6H warnings
            </div>
            <IssueList items={liveGate.warnings} empty="No warnings" />
          </div>
        </section>
      )}

      {simulations && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="single-internal-live-gate-simulation"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                Single Internal Live Gate Simulation
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6I prepares, approves, runs, and rolls back an
                internal-only simulation. It does not call WhatsApp,
                Razorpay, PayU, Delhivery, Vapi, NVIDIA, or OpenAI
                side-effect endpoints.
              </p>
            </div>
            <StatusPill tone={simulations.killSwitchActive ? "success" : "danger"}>
              Kill switch {simulations.killSwitchActive ? "active" : "inactive"}
            </StatusPill>
          </div>

          <div className="grid gap-3 px-6 py-4 sm:grid-cols-5">
            <KeyValue
              label="Default operation"
              value={simulations.defaultOperation}
            />
            <KeyValue label="Dry-run" value={String(simulations.dryRun)} />
            <KeyValue
              label="Live allowed"
              value={String(simulations.liveExecutionAllowed)}
            />
            <KeyValue
              label="External call"
              value={String(simulations.externalCallWillBeMade)}
            />
            <KeyValue
              label="Provider attempted"
              value={String(simulations.providerCallAttempted)}
            />
          </div>

          <div className="grid gap-4 border-t border-border px-6 py-4 lg:grid-cols-[0.8fr_1.2fr]">
            <div className="space-y-3">
              <h4 className="flex items-center gap-2 font-display text-base font-semibold">
                <CheckCircle2 className="h-4 w-4 text-primary" />
                Simulation Controls State
              </h4>
              <KeyValue
                label="Allowed operations"
                value={String(simulations.allowedOperations.length)}
              />
              <KeyValue
                label="Simulations"
                value={String(simulations.count)}
              />
              <KeyValue
                label="External call made"
                value={String(simulations.externalCallWasMade)}
              />
              <KeyValue
                label="Next action"
                value={simulations.summary?.nextAction ?? "prepare_simulation"}
              />
              <div className="rounded-md border border-border bg-warning/5 p-3 text-xs text-muted-foreground">
                Approving or running a Phase 6I simulation does not execute
                external calls.
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full min-w-[860px] text-sm">
                <thead className="bg-muted/30 text-[11px] uppercase text-muted-foreground">
                  <tr>
                    <th className="px-6 py-3 text-left font-medium">
                      Operation
                    </th>
                    <th className="py-3 text-left font-medium">Provider</th>
                    <th className="py-3 text-left font-medium">Status</th>
                    <th className="py-3 text-left font-medium">Approval</th>
                    <th className="py-3 text-left font-medium">Decision</th>
                    <th className="px-6 py-3 text-left font-medium">
                      Provider call
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {simulations.simulations.map((simulation) => (
                    <LiveGateSimulationRow
                      key={simulation.id}
                      simulation={simulation}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="border-t border-border bg-warning/5 px-6 py-3 text-xs text-muted-foreground">
            Allowed operations: {simulations.allowedOperations.join(", ")}.
            Global kill switch remains active; all execution flags remain
            false.
          </div>
        </section>
      )}

      {providerTestPlans && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="provider-test-plan-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ClipboardList className="h-5 w-5 text-primary" />
                Single Internal Provider Test Plan
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6J planning only. Razorpay test-mode create_order
                is the implementation target. No external provider call
                is made in Phase 6J. Approval here unlocks the future
                Phase 6K execution gate, NOT execution itself.
              </p>
            </div>
            <StatusPill
              tone={
                providerTestPlans.safeToStartPhase6K ? "success" : "warning"
              }
            >
              {providerTestPlans.safeToStartPhase6K
                ? "Phase 6K ready"
                : "Phase 6K blocked"}
            </StatusPill>
          </div>
          <div className="grid gap-3 px-6 py-4 sm:grid-cols-4">
            <KeyValue
              label="Latest plan"
              value={
                providerTestPlans.latestPlan?.planId ?? "no plan yet"
              }
            />
            <KeyValue label="Provider" value="Razorpay" />
            <KeyValue label="Operation" value="razorpay.create_order" />
            <KeyValue
              label="Environment"
              value={
                providerTestPlans.latestPlan?.providerEnvironment ?? "test"
              }
            />
          </div>
          <div className="grid gap-4 px-6 pb-4 lg:grid-cols-2">
            <ProviderTestPlanInvariants plan={providerTestPlans.latestPlan} />
            <ProviderTestPlanEnvReadiness
              plan={providerTestPlans.latestPlan}
            />
          </div>
          <div className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground">
            <strong>Read-only.</strong> No "Execute Razorpay" / "Create
            Order" / "Create Payment Link" buttons exist on this page.
            Approval only marks the plan as ready for the future Phase
            6K execution gate.
          </div>
          <div className="border-t border-border bg-warning/5 px-6 py-3 text-xs text-muted-foreground">
            Next action:{" "}
            <span className="font-medium">
              {providerTestPlans.nextAction}
            </span>
          </div>
        </section>
      )}

      {providerExecutionGate && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="provider-execution-gate-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <CreditCard className="h-5 w-5 text-primary" />
                Single Internal Razorpay Test-Mode Execution Gate
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6K. Razorpay test-mode <code>create_order</code>{" "}
                only — synthetic ₹1.00 (100 paise) payload, no
                customer data, no payment link, no capture, no business
                mutation. Actual provider call is{" "}
                <strong>CLI-only</strong> via{" "}
                <code>manage.py execute_single_razorpay_test_order</code>{" "}
                with the <code>--confirm-test-execution</code> flag.
              </p>
            </div>
            <StatusPill
              tone={
                providerExecutionGate.safeToRunPhase6KExecution
                  ? "success"
                  : "warning"
              }
            >
              {providerExecutionGate.safeToRunPhase6KExecution
                ? "Ready (CLI only)"
                : "Gate blocked"}
            </StatusPill>
          </div>
          <div className="grid gap-3 px-6 py-4 sm:grid-cols-4">
            <KeyValue
              label="Approved plan"
              value={
                providerExecutionGate.latestApprovedPlan?.planId ??
                "no approved plan"
              }
            />
            <KeyValue
              label="Successful executions"
              value={String(providerExecutionGate.successfulExecutionCount)}
            />
            <KeyValue
              label="Provider calls attempted"
              value={String(providerExecutionGate.providerCallAttemptedCount)}
            />
            <KeyValue
              label="Business mutations"
              value={String(providerExecutionGate.businessMutationCount)}
            />
          </div>
          <div className="grid gap-4 px-6 pb-4 lg:grid-cols-2">
            <ProviderExecutionEnvCard
              env={providerExecutionGate.envReadiness}
            />
            <ProviderExecutionInvariants
              attempt={providerExecutionGate.latestAttempt}
            />
          </div>
          <ProviderExecutionAttemptsTable
            attempts={providerExecutionGate.attempts}
          />
          <div className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground">
            <strong>Read-only.</strong> No "Execute Razorpay" / "Create
            Order" / "Create Payment Link" buttons exist on this page.
            Phase 6K provider execution is exclusively triggered by
            the CLI command after every gate is satisfied.
          </div>
          <div className="border-t border-border bg-warning/5 px-6 py-3 text-xs text-muted-foreground">
            Next action:{" "}
            <span className="font-medium">
              {providerExecutionGate.nextAction}
            </span>
          </div>
        </section>
      )}

      {(razorpayAuditReview || razorpayWebhookReadiness || razorpayWebhookPlan) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="razorpay-audit-webhook-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <FileSearch className="h-5 w-5 text-primary" />
                Razorpay Test Execution Audit + Webhook Readiness
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6L — read-only review of the Phase 6K Razorpay
                test-mode execution audit trail + the planning policy
                for the future Razorpay webhook receiver. No new
                Razorpay calls. No payment / order status mutation.
              </p>
            </div>
            {razorpayAuditReview && (
              <StatusPill
                tone={razorpayAuditReview.passed ? "success" : "warning"}
              >
                {razorpayAuditReview.passed
                  ? "Audit PASS"
                  : "Audit FAIL"}
              </StatusPill>
            )}
          </div>
          {razorpayAuditReview && (
            <RazorpayAuditReviewCard review={razorpayAuditReview} />
          )}
          {razorpayWebhookReadiness && (
            <RazorpayWebhookReadinessCard
              readiness={razorpayWebhookReadiness}
            />
          )}
          {razorpayWebhookPlan && (
            <RazorpayWebhookPlanCard plan={razorpayWebhookPlan} />
          )}
          <div className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground">
            <strong>Read-only.</strong> Phase 6L never registers a
            webhook receiver, never calls Razorpay, never mutates a
            business row, never exposes raw secrets. Webhook handler
            ships in Phase 6M.
          </div>
        </section>
      )}

      {(razorpayWebhookHandlerReadiness || razorpayWebhookEvents) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="razorpay-webhook-handler-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <Webhook className="h-5 w-5 text-primary" />
                Razorpay Webhook Handler (Test Mode)
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6M — receives, verifies, dedupes, and audits
                Razorpay test-mode webhook events. <strong>No business
                mutation</strong> in this phase. No customer
                notification. No raw payload / signature / secret in the
                UI. Phase 6N will own business-mutation sandbox.
              </p>
            </div>
            {razorpayWebhookHandlerReadiness && (
              <StatusPill
                tone={
                  razorpayWebhookHandlerReadiness.safeToReceiveTestWebhooks
                    ? "success"
                    : "warning"
                }
              >
                {razorpayWebhookHandlerReadiness.webhookTestModeEnabled
                  ? "Receiver enabled"
                  : "Receiver disabled (safe)"}
              </StatusPill>
            )}
          </div>
          {razorpayWebhookHandlerReadiness && (
            <RazorpayWebhookHandlerReadinessCard
              readiness={razorpayWebhookHandlerReadiness}
            />
          )}
          {razorpayWebhookEvents && (
            <RazorpayWebhookEventsTable response={razorpayWebhookEvents} />
          )}
          <div className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground">
            <strong>Read-only.</strong> No "Capture Payment" / "Send
            WhatsApp" / "Mark Order Paid" / "Replay Event" buttons
            exist on this page. Even the simulator runs through the
            same Phase 6M handler — synthetic payload only, no
            external Razorpay call.
          </div>
        </section>
      )}

      {(razorpayBusinessMutationSandboxPlan ||
        razorpayBusinessMutationSandboxReadiness) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="razorpay-business-mutation-sandbox-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <Webhook className="h-5 w-5 text-primary" />
                Razorpay Business Mutation Sandbox Plan
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6N — planning + readiness layer only.{" "}
                <strong>No business mutation</strong>, no customer
                notification, no Razorpay API call, no env-flag flip.
                Phase 6O will own any sandbox-only mutation against
                synthetic test orders, behind a new env flag, gated by
                Director sign-off.
              </p>
            </div>
            {razorpayBusinessMutationSandboxReadiness && (
              <div data-testid="phase6n-safe-to-start-phase6o-badge">
                <StatusPill
                  tone={
                    razorpayBusinessMutationSandboxReadiness.safeToStartPhase6O
                      ? "success"
                      : "warning"
                  }
                >
                  {razorpayBusinessMutationSandboxReadiness.safeToStartPhase6O
                    ? "Ready for Phase 6O planning"
                    : "Blocked — fix Phase 6M state first"}
                </StatusPill>
              </div>
            )}
          </div>

          {razorpayBusinessMutationSandboxReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={razorpayBusinessMutationSandboxReadiness.phase}
              />
              <KeyValue
                label="Status"
                value={razorpayBusinessMutationSandboxReadiness.status}
              />
              <KeyValue
                label="Latest completed"
                value={
                  razorpayBusinessMutationSandboxReadiness.latestCompletedPhase
                }
              />
              <KeyValue
                label="Next phase"
                value={razorpayBusinessMutationSandboxReadiness.nextPhase}
              />
              <KeyValue label="Business mutation" value="Disabled" />
              <KeyValue label="Customer notification" value="Disabled" />
              <KeyValue label="Raw payload storage" value="Disabled" />
              <KeyValue
                label="Phase 6M flags locked off"
                value={
                  razorpayBusinessMutationSandboxReadiness.phase6MFlagsLockedOff
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="Safety counters zero"
                value={
                  razorpayBusinessMutationSandboxReadiness.safetyCountersZero
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="Plan complete"
                value={
                  razorpayBusinessMutationSandboxReadiness.planComplete
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="Event mappings"
                value={String(
                  razorpayBusinessMutationSandboxReadiness.eventMappingCount,
                )}
              />
              <KeyValue
                label="Manual review items"
                value={String(
                  razorpayBusinessMutationSandboxReadiness.manualReviewChecklistSize,
                )}
              />
            </div>
          )}

          {razorpayBusinessMutationSandboxReadiness && (
            <div className="px-6 pb-3 text-xs text-muted-foreground">
              <strong>Next action:</strong>{" "}
              {razorpayBusinessMutationSandboxReadiness.nextAction}
            </div>
          )}

          {razorpayBusinessMutationSandboxPlan && (
            <div className="px-6 pb-4">
              <h4 className="text-sm font-semibold mb-2">
                Event-to-status mapping (Phase 6O target)
              </h4>
              <div className="overflow-x-auto">
                <table
                  className="w-full text-xs"
                  data-testid="phase6n-event-mapping-table"
                >
                  <thead className="text-muted-foreground">
                    <tr className="text-left">
                      <th className="py-1 pr-3">Event</th>
                      <th className="py-1 pr-3">Future sandbox payment</th>
                      <th className="py-1 pr-3">Future order effect</th>
                      <th className="py-1 pr-3">Mutation in 6N</th>
                      <th className="py-1 pr-3">Manual review</th>
                      <th className="py-1 pr-3">Notify</th>
                      <th className="py-1 pr-3">Shipment</th>
                      <th className="py-1 pr-3">Discount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {razorpayBusinessMutationSandboxPlan.eventMappings.map(
                      (row) => (
                        <tr
                          key={row.razorpayEventName}
                          className="border-t border-border"
                        >
                          <td className="py-1 pr-3 font-mono">
                            {row.razorpayEventName}
                          </td>
                          <td className="py-1 pr-3">
                            {row.futureSandboxPaymentStatus}
                          </td>
                          <td className="py-1 pr-3">
                            {row.futureSandboxOrderEffect}
                          </td>
                          <td className="py-1 pr-3 text-emerald-600 font-medium">
                            Disabled
                          </td>
                          <td className="py-1 pr-3">
                            {row.manualReviewRequired ? "Required" : "—"}
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {razorpayBusinessMutationSandboxPlan && (
            <div className="px-6 pb-4 grid gap-4 lg:grid-cols-3">
              <div>
                <h4 className="text-sm font-semibold mb-2">
                  Synthetic-order eligibility
                </h4>
                <ul className="text-xs space-y-1 list-disc pl-5">
                  {Object.entries(
                    razorpayBusinessMutationSandboxPlan.syntheticEligibilityPolicy,
                  )
                    .filter(([, value]) => value === true)
                    .slice(0, 12)
                    .map(([key]) => (
                      <li key={key} className="text-muted-foreground">
                        {key}
                      </li>
                    ))}
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-semibold mb-2">
                  Manual review checklist
                </h4>
                <ul
                  className="text-xs space-y-1 list-disc pl-5"
                  data-testid="phase6n-manual-review-list"
                >
                  {razorpayBusinessMutationSandboxPlan.manualReviewChecklist.map(
                    (entry) => (
                      <li key={entry.key} className="text-muted-foreground">
                        <strong>{entry.key}</strong> — {entry.description}
                      </li>
                    ),
                  )}
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-semibold mb-2">Rollback plan</h4>
                <ol
                  className="text-xs space-y-1 list-decimal pl-5"
                  data-testid="phase6n-rollback-list"
                >
                  {razorpayBusinessMutationSandboxPlan.rollbackPlan.rollbackSteps.map(
                    (step) => (
                      <li key={step.order} className="text-muted-foreground">
                        {step.action}
                      </li>
                    ),
                  )}
                </ol>
                <p className="text-[11px] text-muted-foreground mt-2">
                  Rollback owned by operator; Phase 6N never executes
                  rollback automatically.
                </p>
              </div>
            </div>
          )}

          {razorpayBusinessMutationSandboxPlan && (
            <div className="px-6 pb-4">
              <h4 className="text-sm font-semibold mb-2">Forbidden actions</h4>
              <div
                className="flex flex-wrap gap-1 text-[11px]"
                data-testid="phase6n-forbidden-actions"
              >
                {razorpayBusinessMutationSandboxPlan.forbiddenActions.map(
                  (action) => (
                    <span
                      key={action}
                      className="rounded border border-border bg-muted/30 px-2 py-0.5 font-mono"
                    >
                      {action}
                    </span>
                  ),
                )}
              </div>
            </div>
          )}

          <div className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground">
            <strong>Read-only.</strong> No "Mark Paid" / "Capture
            Payment" / "Refund" / "Send WhatsApp" / "Create Payment
            Link" / "Mutate Order" / "Execute Webhook" / "Replay
            Event" / "Enable Mutation" / "Go Live" / "Run MCP Tool"
            buttons exist on this page. Phase 6N is planning only;
            Phase 6P remains future.
          </div>
        </section>
      )}

      {(razorpaySandboxStatusMappingReadiness || razorpaySandboxStatusReviews) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="razorpay-sandbox-status-mapping-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <Webhook className="h-5 w-5 text-primary" />
                Razorpay Sandbox Status Mapping + Manual Review
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6O — sandbox-review-only.{" "}
                <strong>No business mutation</strong>, no customer
                notification, no Razorpay API call. Approving a review
                here only marks it{" "}
                <code>approved_for_future_phase6p</code> — Phase 6P
                will own any sandbox-only mutation against synthetic
                test orders, gated by Director sign-off.
              </p>
            </div>
            {razorpaySandboxStatusMappingReadiness && (
              <div data-testid="phase6o-safe-to-start-phase6p-badge">
                <StatusPill
                  tone={
                    razorpaySandboxStatusMappingReadiness.safeToStartPhase6P
                      ? "success"
                      : "warning"
                  }
                >
                  {razorpaySandboxStatusMappingReadiness.safeToStartPhase6P
                    ? "Ready for Phase 6P planning"
                    : "Blocked — needs approved review for future Phase 6P"}
                </StatusPill>
              </div>
            )}
          </div>

          {razorpaySandboxStatusMappingReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={razorpaySandboxStatusMappingReadiness.phase}
              />
              <KeyValue
                label="Status"
                value={razorpaySandboxStatusMappingReadiness.status}
              />
              <KeyValue
                label="Latest completed"
                value={
                  razorpaySandboxStatusMappingReadiness.latestCompletedPhase
                }
              />
              <KeyValue
                label="Next phase"
                value={razorpaySandboxStatusMappingReadiness.nextPhase}
              />
              <KeyValue
                label="Sandbox flag"
                value={
                  razorpaySandboxStatusMappingReadiness.razorpaySandboxStatusMappingEnabled
                    ? "Enabled"
                    : "Disabled"
                }
              />
              <KeyValue label="Business mutation" value="Disabled" />
              <KeyValue label="Customer notification" value="Disabled" />
              <KeyValue label="Provider call" value="Disabled" />
              <KeyValue
                label="Reviews pending"
                value={String(
                  razorpaySandboxStatusMappingReadiness.reviewCounts
                    .pendingManualReview,
                )}
              />
              <KeyValue
                label="Reviews approved (for 6P)"
                value={String(
                  razorpaySandboxStatusMappingReadiness.reviewCounts
                    .approvedForFuturePhase6P,
                )}
              />
              <KeyValue
                label="Reviews rejected"
                value={String(
                  razorpaySandboxStatusMappingReadiness.reviewCounts.rejected,
                )}
              />
              <KeyValue
                label="Reviews archived"
                value={String(
                  razorpaySandboxStatusMappingReadiness.reviewCounts.archived,
                )}
              />
            </div>
          )}

          {razorpaySandboxStatusMappingReadiness && (
            <div className="px-6 pb-2 text-xs text-muted-foreground">
              <strong>Next action:</strong>{" "}
              {razorpaySandboxStatusMappingReadiness.nextAction}
            </div>
          )}

          {razorpaySandboxStatusMappingReadiness && (
            <div className="px-6 pb-4">
              <h4 className="text-sm font-semibold mb-2">
                Event-to-status mapping (Phase 6P target)
              </h4>
              <div className="overflow-x-auto">
                <table
                  className="w-full text-xs"
                  data-testid="phase6o-event-mapping-table"
                >
                  <thead className="text-muted-foreground">
                    <tr className="text-left">
                      <th className="py-1 pr-3">Event</th>
                      <th className="py-1 pr-3">Future sandbox payment</th>
                      <th className="py-1 pr-3">Future order effect</th>
                      <th className="py-1 pr-3">Mutation in 6O</th>
                      <th className="py-1 pr-3">Manual review</th>
                      <th className="py-1 pr-3">Notify</th>
                      <th className="py-1 pr-3">Shipment</th>
                      <th className="py-1 pr-3">Discount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {razorpaySandboxStatusMappingReadiness.eventMappings.map(
                      (row) => (
                        <tr
                          key={row.razorpayEventName}
                          className="border-t border-border"
                        >
                          <td className="py-1 pr-3 font-mono">
                            {row.razorpayEventName}
                          </td>
                          <td className="py-1 pr-3">
                            {row.futureSandboxPaymentStatus}
                          </td>
                          <td className="py-1 pr-3">
                            {row.futureSandboxOrderEffect}
                          </td>
                          <td className="py-1 pr-3 text-emerald-600 font-medium">
                            Disabled
                          </td>
                          <td className="py-1 pr-3">
                            {row.manualReviewRequired ? "Required" : "—"}
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {razorpaySandboxStatusReviews && (
            <div className="px-6 pb-4">
              <h4 className="text-sm font-semibold mb-2">
                Sandbox status reviews ({razorpaySandboxStatusReviews.items.length})
              </h4>
              {razorpaySandboxStatusReviews.items.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No reviews prepared yet. Reviews are created via the
                  backend CLI / API only — there is no "Apply Mutation"
                  path in Phase 6O.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table
                    className="w-full text-xs"
                    data-testid="phase6o-reviews-table"
                  >
                    <thead className="text-muted-foreground">
                      <tr className="text-left">
                        <th className="py-1 pr-3">ID</th>
                        <th className="py-1 pr-3">Event</th>
                        <th className="py-1 pr-3">Source event id</th>
                        <th className="py-1 pr-3">Proposed payment</th>
                        <th className="py-1 pr-3">Proposed order effect</th>
                        <th className="py-1 pr-3">Status</th>
                        <th className="py-1 pr-3">Mutation in 6O</th>
                        <th className="py-1 pr-3">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {razorpaySandboxStatusReviews.items.map((row) => (
                        <Phase6OReviewRow
                          key={row.id}
                          row={row}
                          pending={phase6oActionPending === row.id}
                          onAction={async (action, reason) => {
                            setPhase6oActionPending(row.id);
                            setPhase6oActionMessage("");
                            try {
                              const fn =
                                action === "approve"
                                  ? api.approveSaasRazorpaySandboxStatusReview
                                  : action === "reject"
                                  ? api.rejectSaasRazorpaySandboxStatusReview
                                  : api.archiveSaasRazorpaySandboxStatusReview;
                              const result = await fn(row.id, reason);
                              if (result.ok) {
                                setPhase6oActionMessage(
                                  `Review ${row.id} ${action}d (review-only). Next: ${result.nextAction}`,
                                );
                                load();
                              } else {
                                setPhase6oActionMessage(
                                  `Action blocked: ${result.blockers.join(", ") || "see backend logs"}`,
                                );
                              }
                            } finally {
                              setPhase6oActionPending(null);
                            }
                          }}
                        />
                      ))}
                    </tbody>
                  </table>
                  {phase6oActionMessage && (
                    <p className="mt-2 text-[11px] text-muted-foreground">
                      {phase6oActionMessage}
                    </p>
                  )}
                </div>
              )}
            </div>
          )}

          {razorpaySandboxStatusMappingReadiness && (
            <div className="px-6 pb-4 grid gap-4 lg:grid-cols-2">
              <div>
                <h4 className="text-sm font-semibold mb-2">
                  Manual review checklist
                </h4>
                <ul
                  className="text-xs space-y-1 list-disc pl-5"
                  data-testid="phase6o-manual-review-list"
                >
                  {razorpaySandboxStatusMappingReadiness.manualReviewChecklist.map(
                    (entry) => (
                      <li key={entry.key} className="text-muted-foreground">
                        <strong>{entry.key}</strong> — {entry.description}
                      </li>
                    ),
                  )}
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-semibold mb-2">Forbidden actions</h4>
                <div
                  className="flex flex-wrap gap-1 text-[11px]"
                  data-testid="phase6o-forbidden-actions"
                >
                  {razorpaySandboxStatusMappingReadiness.forbiddenActions.map(
                    (action) => (
                      <span
                        key={action}
                        className="rounded border border-border bg-muted/30 px-2 py-0.5 font-mono"
                      >
                        {action}
                      </span>
                    ),
                  )}
                </div>
              </div>
            </div>
          )}

          <div className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground">
            <strong>Sandbox review only.</strong> The "Approve Review
            Only" / "Reject Review" / "Archive Review" buttons above
            change the review row's status only — they NEVER mark an
            Order paid, NEVER capture a Payment, NEVER create a
            Shipment, NEVER send a customer notification. No "Apply
            Mutation" / "Mark Paid" / "Execute Payment" / "Capture" /
            "Refund" / "Send WhatsApp" / "Run MCP Tool" buttons exist
            on this page. Phase 6P will own any sandbox-only mutation
            against synthetic test orders, behind a NEW env flag
            distinct from <code>RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED</code>.
          </div>
        </section>
      )}

      {(razorpaySandboxPaidStatusReadiness || razorpaySandboxPaidStatusAttempts) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="razorpay-sandbox-paid-status-mutation-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <Webhook className="h-5 w-5 text-primary" />
                Razorpay Sandbox Paid-Status Mutation Test
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6P — sandbox-ledger-only.{" "}
                <strong>No real Order / Payment / Shipment / DiscountOfferLog mutation</strong>,
                no customer notification, no Razorpay API call.
                Execution is exclusively via CLI — no API endpoint and
                no frontend button can dispatch a Phase 6P mutation.
              </p>
            </div>
            {razorpaySandboxPaidStatusReadiness && (
              <div data-testid="phase6p-safe-to-start-phase6q-badge">
                <StatusPill
                  tone={
                    razorpaySandboxPaidStatusReadiness.safeToStartPhase6Q
                      ? "success"
                      : "warning"
                  }
                >
                  {razorpaySandboxPaidStatusReadiness.safeToStartPhase6Q
                    ? "Ready for Phase 6Q planning"
                    : "Blocked — run a CLI execute + rollback first"}
                </StatusPill>
              </div>
            )}
          </div>

          {razorpaySandboxPaidStatusReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={razorpaySandboxPaidStatusReadiness.phase}
              />
              <KeyValue
                label="Status"
                value={razorpaySandboxPaidStatusReadiness.status}
              />
              <KeyValue
                label="Latest completed"
                value={razorpaySandboxPaidStatusReadiness.latestCompletedPhase}
              />
              <KeyValue
                label="Next phase"
                value={razorpaySandboxPaidStatusReadiness.nextPhase}
              />
              <KeyValue
                label="Sandbox flag"
                value={
                  razorpaySandboxPaidStatusReadiness.razorpaySandboxPaidStatusMutationEnabled
                    ? "Enabled"
                    : "Disabled"
                }
              />
              <KeyValue label="Real Order mutation" value="Disabled" />
              <KeyValue label="Real Payment mutation" value="Disabled" />
              <KeyValue label="Customer notification" value="Disabled" />
              <KeyValue label="Provider call" value="Disabled" />
              <KeyValue
                label="Frontend can execute"
                value={
                  razorpaySandboxPaidStatusReadiness.frontendCanExecute
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="API endpoint can execute"
                value={
                  razorpaySandboxPaidStatusReadiness.apiEndpointCanExecute
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="Execution path"
                value={razorpaySandboxPaidStatusReadiness.executionPath}
              />
              <KeyValue
                label="Approved Phase 6O reviews"
                value={String(
                  razorpaySandboxPaidStatusReadiness.approvedPhase6OReviewCount,
                )}
              />
              <KeyValue
                label="Attempts ever executed"
                value={String(
                  razorpaySandboxPaidStatusReadiness.attemptCounts.everExecuted,
                )}
              />
              <KeyValue
                label="Attempts ever rolled back"
                value={String(
                  razorpaySandboxPaidStatusReadiness.attemptCounts.everRolledBack,
                )}
              />
              <KeyValue
                label="Ledger rows"
                value={String(
                  razorpaySandboxPaidStatusReadiness.ledgerCounts.totalLedgers,
                )}
              />
            </div>
          )}

          {razorpaySandboxPaidStatusReadiness && (
            <div className="px-6 pb-2 text-xs text-muted-foreground">
              <strong>Next action:</strong>{" "}
              {razorpaySandboxPaidStatusReadiness.nextAction}
            </div>
          )}

          {razorpaySandboxPaidStatusReadiness && (
            <div className="px-6 pb-4">
              <h4 className="text-sm font-semibold mb-2">
                Sandbox event-to-ledger mapping
              </h4>
              <div className="overflow-x-auto">
                <table
                  className="w-full text-xs"
                  data-testid="phase6p-event-mapping-table"
                >
                  <thead className="text-muted-foreground">
                    <tr className="text-left">
                      <th className="py-1 pr-3">Event</th>
                      <th className="py-1 pr-3">Sandbox payment status</th>
                      <th className="py-1 pr-3">Sandbox order effect</th>
                      <th className="py-1 pr-3">Real Order mutation</th>
                      <th className="py-1 pr-3">Real Payment mutation</th>
                      <th className="py-1 pr-3">Notify</th>
                      <th className="py-1 pr-3">Provider</th>
                      <th className="py-1 pr-3">Path</th>
                    </tr>
                  </thead>
                  <tbody>
                    {razorpaySandboxPaidStatusReadiness.eventMappings.map(
                      (row) => (
                        <tr
                          key={row.razorpayEventName}
                          className="border-t border-border"
                        >
                          <td className="py-1 pr-3 font-mono">
                            {row.razorpayEventName}
                          </td>
                          <td className="py-1 pr-3">
                            {row.sandboxPaymentStatus}
                          </td>
                          <td className="py-1 pr-3">
                            {row.sandboxOrderEffect}
                          </td>
                          <td className="py-1 pr-3 text-emerald-600 font-medium">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 text-emerald-600 font-medium">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 font-mono text-[11px]">
                            {row.executionPath}
                          </td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {razorpaySandboxPaidStatusAttempts && (
            <div className="px-6 pb-4">
              <h4 className="text-sm font-semibold mb-2">
                Sandbox mutation attempts
                ({razorpaySandboxPaidStatusAttempts.items.length})
              </h4>
              {razorpaySandboxPaidStatusAttempts.items.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No attempts yet. Attempts are created and executed
                  exclusively via the Phase 6P CLI commands —{" "}
                  <code>prepare_razorpay_sandbox_paid_status_mutation</code>,{" "}
                  <code>execute_razorpay_sandbox_paid_status_mutation</code>,{" "}
                  <code>rollback_razorpay_sandbox_paid_status_mutation</code>.
                  This page renders read-only status only.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table
                    className="w-full text-xs"
                    data-testid="phase6p-attempts-table"
                  >
                    <thead className="text-muted-foreground">
                      <tr className="text-left">
                        <th className="py-1 pr-3">ID</th>
                        <th className="py-1 pr-3">Event</th>
                        <th className="py-1 pr-3">Source event id</th>
                        <th className="py-1 pr-3">Status</th>
                        <th className="py-1 pr-3">Action</th>
                        <th className="py-1 pr-3">Real mutation</th>
                        <th className="py-1 pr-3">Notification</th>
                        <th className="py-1 pr-3">Executed at</th>
                        <th className="py-1 pr-3">Rolled back at</th>
                      </tr>
                    </thead>
                    <tbody>
                      {razorpaySandboxPaidStatusAttempts.items.map((row) => (
                        <tr
                          key={row.id}
                          className="border-t border-border"
                        >
                          <td className="py-1 pr-3">{row.id}</td>
                          <td className="py-1 pr-3 font-mono">
                            {row.eventName}
                          </td>
                          <td className="py-1 pr-3 font-mono">
                            {row.sourceEventId}
                          </td>
                          <td className="py-1 pr-3">
                            <StatusPill
                              tone={
                                row.status === "executed"
                                  ? "success"
                                  : row.status === "rolled_back"
                                  ? "info"
                                  : row.status === "failed" ||
                                    row.status === "blocked"
                                  ? "danger"
                                  : row.status === "archived"
                                  ? "neutral"
                                  : "warning"
                              }
                            >
                              {row.status}
                            </StatusPill>
                          </td>
                          <td className="py-1 pr-3 font-mono text-[11px]">
                            {row.requestedAction}
                          </td>
                          <td className="py-1 pr-3 text-emerald-600 font-medium">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                          <td className="py-1 pr-3">{row.executedAt ?? "—"}</td>
                          <td className="py-1 pr-3">
                            {row.rolledBackAt ?? "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {razorpaySandboxPaidStatusReadiness && (
            <div className="px-6 pb-4 grid gap-4 lg:grid-cols-2">
              <div>
                <h4 className="text-sm font-semibold mb-2">CLI-only execution</h4>
                <p className="text-xs text-muted-foreground">
                  Phase 6P mutation paths are intentionally CLI-only.
                  Approving / rejecting in this UI never touches a real
                  business row. Use the operator runbook for the four
                  Phase 6P CLIs:
                </p>
                <ul
                  className="mt-2 text-[11px] font-mono space-y-1 list-disc pl-5"
                  data-testid="phase6p-cli-list"
                >
                  <li>preview_razorpay_sandbox_paid_status_mutation</li>
                  <li>prepare_razorpay_sandbox_paid_status_mutation</li>
                  <li>
                    execute_razorpay_sandbox_paid_status_mutation
                    --confirm-sandbox-paid-status-mutation --director-signoff
                    "..."
                  </li>
                  <li>
                    rollback_razorpay_sandbox_paid_status_mutation
                    --confirm-sandbox-rollback --reason "..."
                  </li>
                  <li>archive_razorpay_sandbox_paid_status_mutation_attempt</li>
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-semibold mb-2">Forbidden actions</h4>
                <div
                  className="flex flex-wrap gap-1 text-[11px]"
                  data-testid="phase6p-forbidden-actions"
                >
                  {razorpaySandboxPaidStatusReadiness.forbiddenActions.map(
                    (action) => (
                      <span
                        key={action}
                        className="rounded border border-border bg-muted/30 px-2 py-0.5 font-mono"
                      >
                        {action}
                      </span>
                    ),
                  )}
                </div>
              </div>
            </div>
          )}

          <div className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground">
            <strong>Sandbox ledger only.</strong> No "Mark Paid" /
            "Capture Payment" / "Refund" / "Apply Payment" / "Apply
            Mutation" / "Mutate Order" / "Send WhatsApp" / "Create
            Payment Link" / "Execute Webhook" / "Replay Event" /
            "Enable Mutation" / "Go Live" / "Run MCP Tool" buttons exist
            on this page. Execution is exclusively via the Phase 6P CLI
            commands above; this page renders status only.
          </div>
        </section>
      )}

      {(razorpayPaymentOrderWorkflowReadiness || razorpayPaymentOrderWorkflowGates) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="razorpay-payment-order-workflow-gate-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <Webhook className="h-5 w-5 text-primary" />
                Razorpay Payment → Order Workflow Safety Gate
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6Q — audit-only safety gate.{" "}
                <strong>No real Order / Payment / Shipment / DiscountOfferLog mutation</strong>,
                no customer notification, no Razorpay API call.
                Approving a gate only marks it{" "}
                <code>approved_for_future_phase6r</code> — gate state
                changes are CLI-only; no API endpoint or frontend
                button dispatches Phase 6Q approval.
              </p>
            </div>
            {razorpayPaymentOrderWorkflowReadiness && (
              <div data-testid="phase6q-safe-to-start-phase6r-badge">
                <StatusPill
                  tone={
                    razorpayPaymentOrderWorkflowReadiness.safeToStartPhase6R
                      ? "success"
                      : "warning"
                  }
                >
                  {razorpayPaymentOrderWorkflowReadiness.safeToStartPhase6R
                    ? "Ready for Phase 6R planning"
                    : "Blocked — needs approved gate review for future Phase 6R"}
                </StatusPill>
              </div>
            )}
          </div>

          {razorpayPaymentOrderWorkflowReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={razorpayPaymentOrderWorkflowReadiness.phase}
              />
              <KeyValue
                label="Status"
                value={razorpayPaymentOrderWorkflowReadiness.status}
              />
              <KeyValue
                label="Latest completed"
                value={razorpayPaymentOrderWorkflowReadiness.latestCompletedPhase}
              />
              <KeyValue
                label="Next phase"
                value={razorpayPaymentOrderWorkflowReadiness.nextPhase}
              />
              <KeyValue
                label="Gate flag"
                value={
                  razorpayPaymentOrderWorkflowReadiness.razorpayPaymentOrderWorkflowGateEnabled
                    ? "Enabled"
                    : "Disabled"
                }
              />
              <KeyValue label="Real Order mutation" value="Disabled" />
              <KeyValue label="Real Payment mutation" value="Disabled" />
              <KeyValue label="Customer notification" value="Disabled" />
              <KeyValue label="Provider call" value="Disabled" />
              <KeyValue
                label="Frontend can execute"
                value={
                  razorpayPaymentOrderWorkflowReadiness.frontendCanExecute
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="API can approve"
                value={
                  razorpayPaymentOrderWorkflowReadiness.apiEndpointCanApprove
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="Execution path"
                value={razorpayPaymentOrderWorkflowReadiness.executionPath}
              />
              <KeyValue
                label="Phase 6P executed"
                value={String(
                  razorpayPaymentOrderWorkflowReadiness.phase6PExecutedCount,
                )}
              />
              <KeyValue
                label="Phase 6P rolled back"
                value={String(
                  razorpayPaymentOrderWorkflowReadiness.phase6PRolledBackCount,
                )}
              />
              <KeyValue
                label="Gates pending"
                value={String(
                  razorpayPaymentOrderWorkflowReadiness.gateCounts
                    .pendingManualReview,
                )}
              />
              <KeyValue
                label="Gates approved (for 6R)"
                value={String(
                  razorpayPaymentOrderWorkflowReadiness.gateCounts
                    .approvedForFuturePhase6R,
                )}
              />
            </div>
          )}

          {razorpayPaymentOrderWorkflowReadiness && (
            <div className="px-6 pb-2 text-xs text-muted-foreground">
              <strong>Next action:</strong>{" "}
              {razorpayPaymentOrderWorkflowReadiness.nextAction}
            </div>
          )}

          {razorpayPaymentOrderWorkflowReadiness && (
            <div className="px-6 pb-4">
              <h4 className="text-sm font-semibold mb-2">
                Payment → Order workflow contract (Phase 6R target)
              </h4>
              <div className="overflow-x-auto">
                <table
                  className="w-full text-xs"
                  data-testid="phase6q-contract-table"
                >
                  <thead className="text-muted-foreground">
                    <tr className="text-left">
                      <th className="py-1 pr-3">Event</th>
                      <th className="py-1 pr-3">Future payment</th>
                      <th className="py-1 pr-3">Future order status</th>
                      <th className="py-1 pr-3">Workflow action</th>
                      <th className="py-1 pr-3">Mutation in 6Q</th>
                      <th className="py-1 pr-3">Notify</th>
                      <th className="py-1 pr-3">Provider</th>
                      <th className="py-1 pr-3">Shipment</th>
                    </tr>
                  </thead>
                  <tbody>
                    {razorpayPaymentOrderWorkflowReadiness.workflowContract.map(
                      (row) => (
                        <tr
                          key={row.razorpayEventName}
                          className="border-t border-border"
                        >
                          <td className="py-1 pr-3 font-mono">
                            {row.razorpayEventName}
                          </td>
                          <td className="py-1 pr-3">
                            {row.futurePaymentStatus}
                          </td>
                          <td className="py-1 pr-3">
                            {row.futureOrderStatusCandidate}
                          </td>
                          <td className="py-1 pr-3 font-mono text-[11px]">
                            {row.workflowAction}
                          </td>
                          <td className="py-1 pr-3 text-emerald-600 font-medium">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {razorpayPaymentOrderWorkflowGates && (
            <div className="px-6 pb-4">
              <h4 className="text-sm font-semibold mb-2">
                Workflow gate review records (
                {razorpayPaymentOrderWorkflowGates.items.length})
              </h4>
              {razorpayPaymentOrderWorkflowGates.items.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No gate reviews yet. Gate reviews are prepared,
                  approved, rejected, and archived exclusively via
                  the Phase 6Q CLI commands —{" "}
                  <code>prepare_razorpay_payment_order_workflow_gate</code>,{" "}
                  <code>approve_razorpay_payment_order_workflow_gate</code>,{" "}
                  <code>reject_razorpay_payment_order_workflow_gate</code>,{" "}
                  <code>archive_razorpay_payment_order_workflow_gate</code>.
                  This page renders read-only status only.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table
                    className="w-full text-xs"
                    data-testid="phase6q-gates-table"
                  >
                    <thead className="text-muted-foreground">
                      <tr className="text-left">
                        <th className="py-1 pr-3">ID</th>
                        <th className="py-1 pr-3">Event</th>
                        <th className="py-1 pr-3">Source event id</th>
                        <th className="py-1 pr-3">Status</th>
                        <th className="py-1 pr-3">Real mutation</th>
                        <th className="py-1 pr-3">Notification</th>
                        <th className="py-1 pr-3">Reviewed at</th>
                        <th className="py-1 pr-3">Archived at</th>
                      </tr>
                    </thead>
                    <tbody>
                      {razorpayPaymentOrderWorkflowGates.items.map((row) => (
                        <tr
                          key={row.id}
                          className="border-t border-border"
                        >
                          <td className="py-1 pr-3">{row.id}</td>
                          <td className="py-1 pr-3 font-mono">
                            {row.eventName}
                          </td>
                          <td className="py-1 pr-3 font-mono">
                            {row.sourceEventId}
                          </td>
                          <td className="py-1 pr-3">
                            <StatusPill
                              tone={
                                row.status === "approved_for_future_phase6r"
                                  ? "success"
                                  : row.status === "rejected" ||
                                    row.status === "blocked"
                                  ? "danger"
                                  : row.status === "archived"
                                  ? "neutral"
                                  : "warning"
                              }
                            >
                              {row.status}
                            </StatusPill>
                          </td>
                          <td className="py-1 pr-3 text-emerald-600 font-medium">
                            Disabled
                          </td>
                          <td className="py-1 pr-3 text-emerald-600">
                            Disabled
                          </td>
                          <td className="py-1 pr-3">
                            {row.reviewedAt ?? "—"}
                          </td>
                          <td className="py-1 pr-3">
                            {row.archivedAt ?? "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {razorpayPaymentOrderWorkflowReadiness && (
            <div className="px-6 pb-4 grid gap-4 lg:grid-cols-2">
              <div>
                <h4 className="text-sm font-semibold mb-2">CLI-only review</h4>
                <p className="text-xs text-muted-foreground">
                  Phase 6Q gate state changes are intentionally
                  CLI-only. Approving / rejecting / archiving in this
                  UI is not exposed. Use the operator runbook for the
                  Phase 6Q CLIs:
                </p>
                <ul
                  className="mt-2 text-[11px] font-mono space-y-1 list-disc pl-5"
                  data-testid="phase6q-cli-list"
                >
                  <li>preview_razorpay_payment_order_workflow_gate</li>
                  <li>prepare_razorpay_payment_order_workflow_gate</li>
                  <li>
                    approve_razorpay_payment_order_workflow_gate --reason "..."
                  </li>
                  <li>
                    reject_razorpay_payment_order_workflow_gate --reason "..."
                  </li>
                  <li>
                    archive_razorpay_payment_order_workflow_gate --reason "..."
                  </li>
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-semibold mb-2">Forbidden actions</h4>
                <div
                  className="flex flex-wrap gap-1 text-[11px]"
                  data-testid="phase6q-forbidden-actions"
                >
                  {razorpayPaymentOrderWorkflowReadiness.forbiddenActions.map(
                    (action) => (
                      <span
                        key={action}
                        className="rounded border border-border bg-muted/30 px-2 py-0.5 font-mono"
                      >
                        {action}
                      </span>
                    ),
                  )}
                </div>
              </div>
            </div>
          )}

          <div className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground">
            <strong>Audit gate only.</strong> No "Mark Paid" /
            "Capture Payment" / "Refund" / "Apply Payment" / "Apply
            Mutation" / "Mutate Order" / "Send WhatsApp" / "Create
            Payment Link" / "Execute Webhook" / "Replay Event" /
            "Enable Mutation" / "Go Live" / "Run MCP Tool" / "Execute
            Workflow" / "Apply Order Update" / "Confirm Paid Order" /
            "Start Live Workflow" buttons exist on this page. Gate
            review state changes are exclusively via the Phase 6Q CLI
            commands above.
          </div>
        </section>
      )}

      {(razorpayPaymentDispatchReadiness ||
        razorpayPaymentDispatchReadinessGates) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="razorpay-payment-dispatch-readiness-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <Webhook className="h-5 w-5 text-primary" />
                Razorpay Payment → WhatsApp / Courier Dispatch Readiness
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6R — readiness contract only.{" "}
                <strong>
                  No WhatsApp send, no Meta Cloud call, no Delhivery call,
                  no shipment / AWB creation, no real Order / Payment /
                  Customer / Lead mutation, no Razorpay API call
                </strong>
                . Approving a readiness gate only marks it{" "}
                <code>approved_for_future_phase6s</code> — review state
                changes are CLI-only; no API endpoint or frontend button
                dispatches Phase 6R approval.
              </p>
            </div>
            {razorpayPaymentDispatchReadiness && (
              <div data-testid="phase6r-safe-to-start-phase6s-badge">
                <StatusPill
                  tone={
                    razorpayPaymentDispatchReadiness.safeToStartPhase6S
                      ? "success"
                      : "warning"
                  }
                >
                  {razorpayPaymentDispatchReadiness.safeToStartPhase6S
                    ? "Ready for Phase 6S planning"
                    : "Blocked — needs approved readiness review for future Phase 6S"}
                </StatusPill>
              </div>
            )}
          </div>

          {razorpayPaymentDispatchReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={razorpayPaymentDispatchReadiness.phase}
              />
              <KeyValue
                label="Status"
                value={razorpayPaymentDispatchReadiness.status}
              />
              <KeyValue
                label="Latest completed"
                value={razorpayPaymentDispatchReadiness.latestCompletedPhase}
              />
              <KeyValue
                label="Next phase"
                value={razorpayPaymentDispatchReadiness.nextPhase}
              />
              <KeyValue
                label="Readiness flag"
                value={
                  razorpayPaymentDispatchReadiness.razorpayPaymentDispatchReadinessEnabled
                    ? "Enabled"
                    : "Disabled"
                }
              />
              <KeyValue label="WhatsApp send" value="Disabled" />
              <KeyValue label="Meta Cloud call" value="Disabled" />
              <KeyValue label="Delhivery call" value="Disabled" />
              <KeyValue label="Shipment creation" value="Disabled" />
              <KeyValue label="Customer notification" value="Disabled" />
              <KeyValue label="Provider call" value="Disabled" />
              <KeyValue
                label="Frontend can execute"
                value={
                  razorpayPaymentDispatchReadiness.frontendCanExecute
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="API can approve"
                value={
                  razorpayPaymentDispatchReadiness.apiEndpointCanApprove
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="Execution path"
                value={razorpayPaymentDispatchReadiness.executionPath}
              />
              <KeyValue
                label="Phase 6Q approved gates"
                value={String(
                  razorpayPaymentDispatchReadiness.phase6QApprovedGateCount,
                )}
              />
              <KeyValue
                label="Pending readiness reviews"
                value={String(
                  razorpayPaymentDispatchReadiness.readinessCounts
                    .pendingManualReview,
                )}
              />
              <KeyValue
                label="Approved for future 6S"
                value={String(
                  razorpayPaymentDispatchReadiness.readinessCounts
                    .approvedForFuturePhase6S,
                )}
              />
            </div>
          )}

          {razorpayPaymentDispatchReadiness && (
            <div className="px-6 pb-4 text-xs text-muted-foreground">
              <strong>Next action:</strong>{" "}
              {razorpayPaymentDispatchReadiness.nextAction}
            </div>
          )}

          {razorpayPaymentDispatchReadiness && (
            <div className="px-6 pb-4">
              <h4 className="text-sm font-semibold mb-2">
                Readiness contract (9 events)
              </h4>
              <div className="overflow-x-auto rounded border border-border">
                <table className="w-full text-xs">
                  <thead className="bg-muted/40">
                    <tr className="text-left">
                      <th className="px-3 py-2">Event</th>
                      <th className="px-3 py-2">WhatsApp readiness</th>
                      <th className="px-3 py-2">Courier readiness</th>
                      <th className="px-3 py-2">Dispatch readiness</th>
                      <th className="px-3 py-2">Send allowed in 6R</th>
                      <th className="px-3 py-2">Courier in 6R</th>
                    </tr>
                  </thead>
                  <tbody>
                    {razorpayPaymentDispatchReadiness.readinessContract.map(
                      (row) => (
                        <tr
                          key={row.razorpayEventName}
                          className="border-t border-border"
                        >
                          <td className="px-3 py-2 font-mono">
                            {row.razorpayEventName}
                          </td>
                          <td className="px-3 py-2 font-mono">
                            {row.futureWhatsAppReadinessAction}
                          </td>
                          <td className="px-3 py-2 font-mono">
                            {row.futureCourierReadinessAction}
                          </td>
                          <td className="px-3 py-2 font-mono">
                            {row.futureDispatchReadinessAction}
                          </td>
                          <td className="px-3 py-2">No</td>
                          <td className="px-3 py-2">No</td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {razorpayPaymentDispatchReadinessGates && (
            <div className="px-6 pb-4">
              <h4 className="text-sm font-semibold mb-2">
                Recent readiness gates ({" "}
                {razorpayPaymentDispatchReadinessGates.items.length})
              </h4>
              {razorpayPaymentDispatchReadinessGates.items.length === 0 ? (
                <div className="rounded border border-dashed border-border bg-muted/30 px-4 py-3 text-xs text-muted-foreground">
                  No readiness gates recorded yet. Run the Phase 6R CLI
                  commands —{" "}
                  <code>
                    inspect_razorpay_payment_dispatch_readiness
                  </code>
                  ,{" "}
                  <code>
                    prepare_razorpay_payment_dispatch_readiness_gate
                  </code>
                  ,{" "}
                  <code>
                    approve_razorpay_payment_dispatch_readiness_gate
                  </code>
                  ,{" "}
                  <code>
                    reject_razorpay_payment_dispatch_readiness_gate
                  </code>
                  .
                </div>
              ) : (
                <div className="overflow-x-auto rounded border border-border">
                  <table className="w-full text-xs">
                    <thead className="bg-muted/40">
                      <tr className="text-left">
                        <th className="px-3 py-2">ID</th>
                        <th className="px-3 py-2">Event</th>
                        <th className="px-3 py-2">Status</th>
                        <th className="px-3 py-2">WhatsApp action</th>
                        <th className="px-3 py-2">Courier action</th>
                        <th className="px-3 py-2">Dispatch action</th>
                        <th className="px-3 py-2">Sent / Queued / Shipped</th>
                      </tr>
                    </thead>
                    <tbody>
                      {razorpayPaymentDispatchReadinessGates.items.map(
                        (row) => (
                          <tr
                            key={row.id}
                            className="border-t border-border"
                          >
                            <td className="px-3 py-2 font-mono">{row.id}</td>
                            <td className="px-3 py-2 font-mono">
                              {row.eventName}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.status}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.proposedWhatsAppAction}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.proposedCourierAction}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.proposedDispatchReadinessAction}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.whatsAppMessageCreated ? "S" : "-"}
                              {row.whatsAppMessageQueued ? "Q" : "-"}
                              {row.shipmentCreated ? "X" : "-"}
                            </td>
                          </tr>
                        ),
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {razorpayPaymentDispatchReadiness && (
            <div className="px-6 pb-4 grid gap-3 lg:grid-cols-3">
              <div>
                <h4 className="text-sm font-semibold mb-2">
                  WhatsApp readiness checklist
                </h4>
                <ul className="space-y-2 text-xs">
                  {razorpayPaymentDispatchReadiness.whatsAppReadinessChecklist.map(
                    (item) => (
                      <li
                        key={item.key}
                        className="rounded border border-border bg-muted/20 px-3 py-2"
                      >
                        <div className="font-mono text-[11px]">
                          {item.key}
                        </div>
                        <div className="text-muted-foreground">
                          {item.description}
                        </div>
                      </li>
                    ),
                  )}
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-semibold mb-2">
                  Courier readiness checklist
                </h4>
                <ul className="space-y-2 text-xs">
                  {razorpayPaymentDispatchReadiness.courierReadinessChecklist.map(
                    (item) => (
                      <li
                        key={item.key}
                        className="rounded border border-border bg-muted/20 px-3 py-2"
                      >
                        <div className="font-mono text-[11px]">
                          {item.key}
                        </div>
                        <div className="text-muted-foreground">
                          {item.description}
                        </div>
                      </li>
                    ),
                  )}
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-semibold mb-2">
                  Dispatch readiness checklist
                </h4>
                <ul className="space-y-2 text-xs">
                  {razorpayPaymentDispatchReadiness.dispatchReadinessChecklist.map(
                    (item) => (
                      <li
                        key={item.key}
                        className="rounded border border-border bg-muted/20 px-3 py-2"
                      >
                        <div className="font-mono text-[11px]">
                          {item.key}
                        </div>
                        <div className="text-muted-foreground">
                          {item.description}
                        </div>
                      </li>
                    ),
                  )}
                </ul>
              </div>
            </div>
          )}

          {razorpayPaymentDispatchReadiness && (
            <div className="px-6 pb-4">
              <details className="text-xs">
                <summary className="cursor-pointer font-semibold">
                  Phase 6R forbidden actions ({" "}
                  {razorpayPaymentDispatchReadiness.forbiddenActions.length}
                  )
                </summary>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {razorpayPaymentDispatchReadiness.forbiddenActions.map(
                    (action) => (
                      <span
                        key={action}
                        className="rounded border border-border bg-muted/30 px-2 py-0.5 font-mono"
                      >
                        {action}
                      </span>
                    ),
                  )}
                </div>
              </details>
            </div>
          )}

          <div className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground">
            <strong>Readiness contract only.</strong> No "Send WhatsApp"
            / "Queue WhatsApp" / "Create Shipment" / "Create AWB" /
            "Book Courier" / "Dispatch Order" / "Notify Customer" /
            "Mark Paid" / "Capture Payment" / "Refund" / "Apply
            Mutation" / "Mutate Order" / "Create Payment Link" /
            "Execute Webhook" / "Replay Event" / "Enable Mutation" /
            "Go Live" / "Run MCP Tool" / "Execute Workflow" / "Apply
            Order Update" / "Confirm Paid Order" / "Start Live
            Workflow" buttons exist on this page. Readiness review
            state changes are exclusively via the Phase 6R CLI commands
            above.
          </div>
        </section>
      )}

      {(razorpayPaymentDispatchPilotPlanReadiness ||
        razorpayPaymentDispatchPilotPlans) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="razorpay-payment-dispatch-pilot-plan-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <Webhook className="h-5 w-5 text-primary" />
                Razorpay Limited Internal Dispatch Pilot Plan
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6S — pilot planning only.{" "}
                <strong>
                  No pilot execution, no WhatsApp send, no Meta Cloud
                  call, no Delhivery call, no shipment / AWB creation,
                  no real Order / Payment / Customer / Lead mutation,
                  no Razorpay API call
                </strong>
                . Approving a pilot plan only marks it{" "}
                <code>approved_for_future_phase6t</code> — review state
                changes are CLI-only; no API endpoint or frontend button
                dispatches Phase 6S approval.
              </p>
            </div>
            {razorpayPaymentDispatchPilotPlanReadiness && (
              <div data-testid="phase6s-safe-to-start-phase6t-badge">
                <StatusPill
                  tone={
                    razorpayPaymentDispatchPilotPlanReadiness.safeToStartPhase6T
                      ? "success"
                      : "warning"
                  }
                >
                  {razorpayPaymentDispatchPilotPlanReadiness.safeToStartPhase6T
                    ? "Ready for Phase 6T planning"
                    : "Blocked — needs approved pilot plan for future Phase 6T"}
                </StatusPill>
              </div>
            )}
          </div>

          {razorpayPaymentDispatchPilotPlanReadiness && (
            <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue
                label="Phase"
                value={razorpayPaymentDispatchPilotPlanReadiness.phase}
              />
              <KeyValue
                label="Status"
                value={razorpayPaymentDispatchPilotPlanReadiness.status}
              />
              <KeyValue
                label="Latest completed"
                value={
                  razorpayPaymentDispatchPilotPlanReadiness.latestCompletedPhase
                }
              />
              <KeyValue
                label="Next phase"
                value={razorpayPaymentDispatchPilotPlanReadiness.nextPhase}
              />
              <KeyValue
                label="Pilot plan flag"
                value={
                  razorpayPaymentDispatchPilotPlanReadiness.razorpayPaymentDispatchPilotPlanEnabled
                    ? "Enabled"
                    : "Disabled"
                }
              />
              <KeyValue label="Pilot execution" value="Disabled" />
              <KeyValue label="WhatsApp send" value="Disabled" />
              <KeyValue label="WhatsApp queue" value="Disabled" />
              <KeyValue label="Meta Cloud call" value="Disabled" />
              <KeyValue label="Delhivery call" value="Disabled" />
              <KeyValue label="Shipment created" value="Disabled" />
              <KeyValue label="AWB created" value="Disabled" />
              <KeyValue label="Customer notification" value="Disabled" />
              <KeyValue label="Provider call" value="Disabled" />
              <KeyValue
                label="Frontend can execute"
                value={
                  razorpayPaymentDispatchPilotPlanReadiness.frontendCanExecute
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="API can approve"
                value={
                  razorpayPaymentDispatchPilotPlanReadiness.apiEndpointCanApprove
                    ? "Yes"
                    : "No"
                }
              />
              <KeyValue
                label="Execution path"
                value={
                  razorpayPaymentDispatchPilotPlanReadiness.executionPath
                }
              />
              <KeyValue
                label="Phase 6R approved gates"
                value={String(
                  razorpayPaymentDispatchPilotPlanReadiness.phase6RApprovedReadinessGateCount,
                )}
              />
              <KeyValue
                label="Pending pilot plans"
                value={String(
                  razorpayPaymentDispatchPilotPlanReadiness.pilotPlanCounts
                    .pendingManualReview,
                )}
              />
              <KeyValue
                label="Approved for future 6T"
                value={String(
                  razorpayPaymentDispatchPilotPlanReadiness.pilotPlanCounts
                    .approvedForFuturePhase6T,
                )}
              />
              <KeyValue
                label="Max pilot orders"
                value={String(
                  razorpayPaymentDispatchPilotPlanReadiness.maxPilotOrders,
                )}
              />
              <KeyValue
                label="Max amount (paise)"
                value={String(
                  razorpayPaymentDispatchPilotPlanReadiness.maxSafeAmountPaise,
                )}
              />
            </div>
          )}

          {razorpayPaymentDispatchPilotPlanReadiness && (
            <div className="px-6 pb-4 text-xs text-muted-foreground">
              <strong>Next action:</strong>{" "}
              {razorpayPaymentDispatchPilotPlanReadiness.nextAction}
            </div>
          )}

          {razorpayPaymentDispatchPilotPlanReadiness && (
            <div
              className="px-6 pb-4"
              data-testid="phase6s-pilot-contract-table"
            >
              <h4 className="text-sm font-semibold mb-2">
                Limited internal pilot contract (9 events)
              </h4>
              <div className="overflow-x-auto rounded border border-border">
                <table className="w-full text-xs">
                  <thead className="bg-muted/40">
                    <tr className="text-left">
                      <th className="px-3 py-2">Event</th>
                      <th className="px-3 py-2">Pilot eligibility</th>
                      <th className="px-3 py-2">WhatsApp pilot action</th>
                      <th className="px-3 py-2">Courier pilot action</th>
                      <th className="px-3 py-2">Dispatch pilot action</th>
                      <th className="px-3 py-2">Pilot in 6S</th>
                      <th className="px-3 py-2">Send in 6S</th>
                      <th className="px-3 py-2">Courier in 6S</th>
                    </tr>
                  </thead>
                  <tbody>
                    {razorpayPaymentDispatchPilotPlanReadiness.pilotContract.map(
                      (row) => (
                        <tr
                          key={row.razorpayEventName}
                          className="border-t border-border"
                        >
                          <td className="px-3 py-2 font-mono">
                            {row.razorpayEventName}
                          </td>
                          <td className="px-3 py-2 font-mono">
                            {row.futurePilotEligibility}
                          </td>
                          <td className="px-3 py-2 font-mono">
                            {row.futureWhatsAppPilotAction}
                          </td>
                          <td className="px-3 py-2 font-mono">
                            {row.futureCourierPilotAction}
                          </td>
                          <td className="px-3 py-2 font-mono">
                            {row.futureDispatchPilotAction}
                          </td>
                          <td className="px-3 py-2">No</td>
                          <td className="px-3 py-2">No</td>
                          <td className="px-3 py-2">No</td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {razorpayPaymentDispatchPilotPlans && (
            <div className="px-6 pb-4">
              <h4 className="text-sm font-semibold mb-2">
                Recent pilot plans (
                {razorpayPaymentDispatchPilotPlans.items.length})
              </h4>
              {razorpayPaymentDispatchPilotPlans.items.length === 0 ? (
                <div className="rounded border border-dashed border-border bg-muted/30 px-4 py-3 text-xs text-muted-foreground">
                  No pilot plans recorded yet. Run the Phase 6S CLI
                  commands —{" "}
                  <code>
                    inspect_razorpay_payment_dispatch_pilot_plan_readiness
                  </code>
                  ,{" "}
                  <code>
                    prepare_razorpay_payment_dispatch_pilot_plan
                  </code>
                  ,{" "}
                  <code>
                    approve_razorpay_payment_dispatch_pilot_plan
                  </code>
                  ,{" "}
                  <code>
                    reject_razorpay_payment_dispatch_pilot_plan
                  </code>
                  .
                </div>
              ) : (
                <div className="overflow-x-auto rounded border border-border">
                  <table className="w-full text-xs">
                    <thead className="bg-muted/40">
                      <tr className="text-left">
                        <th className="px-3 py-2">ID</th>
                        <th className="px-3 py-2">Event</th>
                        <th className="px-3 py-2">Status</th>
                        <th className="px-3 py-2">Pilot mode</th>
                        <th className="px-3 py-2">WhatsApp action</th>
                        <th className="px-3 py-2">Courier action</th>
                        <th className="px-3 py-2">Dispatch action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {razorpayPaymentDispatchPilotPlans.items.map(
                        (row) => (
                          <tr
                            key={row.id}
                            className="border-t border-border"
                          >
                            <td className="px-3 py-2 font-mono">
                              {row.id}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.eventName}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.status}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.pilotMode}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.proposedWhatsAppAction}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.proposedCourierAction}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.proposedDispatchAction}
                            </td>
                          </tr>
                        ),
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {razorpayPaymentDispatchPilotPlanReadiness && (
            <div className="px-6 pb-4 grid gap-3 lg:grid-cols-2 xl:grid-cols-4">
              <div>
                <h4 className="text-sm font-semibold mb-2">
                  Internal staff cohort checklist
                </h4>
                <ul className="space-y-2 text-xs">
                  {razorpayPaymentDispatchPilotPlanReadiness.internalStaffCohortChecklist.map(
                    (item) => (
                      <li
                        key={item.key}
                        className="rounded border border-border bg-muted/20 px-3 py-2"
                      >
                        <div className="font-mono text-[11px]">
                          {item.key}
                        </div>
                        <div className="text-muted-foreground">
                          {item.description}
                        </div>
                      </li>
                    ),
                  )}
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-semibold mb-2">
                  WhatsApp pilot checklist
                </h4>
                <ul className="space-y-2 text-xs">
                  {razorpayPaymentDispatchPilotPlanReadiness.whatsAppPilotChecklist.map(
                    (item) => (
                      <li
                        key={item.key}
                        className="rounded border border-border bg-muted/20 px-3 py-2"
                      >
                        <div className="font-mono text-[11px]">
                          {item.key}
                        </div>
                        <div className="text-muted-foreground">
                          {item.description}
                        </div>
                      </li>
                    ),
                  )}
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-semibold mb-2">
                  Courier pilot checklist
                </h4>
                <ul className="space-y-2 text-xs">
                  {razorpayPaymentDispatchPilotPlanReadiness.courierPilotChecklist.map(
                    (item) => (
                      <li
                        key={item.key}
                        className="rounded border border-border bg-muted/20 px-3 py-2"
                      >
                        <div className="font-mono text-[11px]">
                          {item.key}
                        </div>
                        <div className="text-muted-foreground">
                          {item.description}
                        </div>
                      </li>
                    ),
                  )}
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-semibold mb-2">
                  Dispatch pilot checklist
                </h4>
                <ul className="space-y-2 text-xs">
                  {razorpayPaymentDispatchPilotPlanReadiness.dispatchPilotChecklist.map(
                    (item) => (
                      <li
                        key={item.key}
                        className="rounded border border-border bg-muted/20 px-3 py-2"
                      >
                        <div className="font-mono text-[11px]">
                          {item.key}
                        </div>
                        <div className="text-muted-foreground">
                          {item.description}
                        </div>
                      </li>
                    ),
                  )}
                </ul>
              </div>
            </div>
          )}

          {razorpayPaymentDispatchPilotPlanReadiness && (
            <div className="px-6 pb-4 grid gap-3 lg:grid-cols-2">
              <div>
                <h4 className="text-sm font-semibold mb-2">
                  Abort criteria
                </h4>
                <ul className="space-y-1 text-xs">
                  {razorpayPaymentDispatchPilotPlanReadiness.abortCriteria.map(
                    (item) => (
                      <li
                        key={item}
                        className="font-mono rounded border border-border bg-muted/20 px-2 py-1"
                      >
                        {item}
                      </li>
                    ),
                  )}
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-semibold mb-2">
                  Verification checklist
                </h4>
                <ul className="space-y-2 text-xs">
                  {razorpayPaymentDispatchPilotPlanReadiness.verificationChecklist.map(
                    (item) => (
                      <li
                        key={item.key}
                        className="rounded border border-border bg-muted/20 px-3 py-2"
                      >
                        <div className="font-mono text-[11px]">
                          {item.key}
                        </div>
                        <div className="text-muted-foreground">
                          {item.description}
                        </div>
                      </li>
                    ),
                  )}
                </ul>
              </div>
            </div>
          )}

          {razorpayPaymentDispatchPilotPlanReadiness && (
            <div className="px-6 pb-4">
              <details className="text-xs">
                <summary
                  className="cursor-pointer font-semibold"
                  data-testid="phase6s-forbidden-actions"
                >
                  Phase 6S forbidden actions ({" "}
                  {
                    razorpayPaymentDispatchPilotPlanReadiness.forbiddenActions
                      .length
                  }
                  )
                </summary>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {razorpayPaymentDispatchPilotPlanReadiness.forbiddenActions.map(
                    (action) => (
                      <span
                        key={action}
                        className="rounded border border-border bg-muted/30 px-2 py-0.5 font-mono"
                      >
                        {action}
                      </span>
                    ),
                  )}
                </div>
              </details>
            </div>
          )}

          <div className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground">
            <strong>Pilot plan only.</strong> No "Start Pilot" / "Run
            Pilot" / "Execute Pilot" / "Start Live Workflow" / "Send
            WhatsApp" / "Queue WhatsApp" / "Notify Customer" / "Create
            Shipment" / "Create AWB" / "Book Courier" / "Dispatch
            Order" / "Call Delhivery" / "Call Meta" / "Mark Paid" /
            "Capture Payment" / "Refund" / "Create Payment Link" /
            "Mutate Order" / "Apply Payment" / "Apply Mutation" /
            "Replay Event" / "Enable Mutation" / "Go Live" / "Run MCP
            Tool" buttons exist on this page. Pilot plan review state
            changes are exclusively via the Phase 6S CLI commands
            above.
          </div>
        </section>
      )}

      {(razorpayPhase6FinalAuditLockReadiness ||
        razorpayPhase6FinalAuditLocks) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="razorpay-phase6-final-audit-lock-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <ShieldCheck className="h-5 w-5 text-primary" />
                Razorpay Phase 6 Final Audit + Lock
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6T - <strong>Final Audit Only</strong>. The view
                composes Phase 6N through Phase 6S into an audit-chain
                attestation and future controlled pilot contract. Review
                state changes are CLI-only; this page is read-only.
              </p>
            </div>
            {razorpayPhase6FinalAuditLockReadiness && (
              <div data-testid="phase6t-safe-to-start-future-controlled-pilot-badge">
                <StatusPill
                  tone={
                    razorpayPhase6FinalAuditLockReadiness.safeToStartFutureControlledPilot
                      ? "success"
                      : "warning"
                  }
                >
                  {razorpayPhase6FinalAuditLockReadiness.safeToStartFutureControlledPilot
                    ? "Decision gate reviewable"
                    : "Decision gate blocked"}
                </StatusPill>
              </div>
            )}
          </div>

          {razorpayPhase6FinalAuditLockReadiness && (
            <>
              <div className="px-6 py-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <KeyValue
                  label="Phase"
                  value={razorpayPhase6FinalAuditLockReadiness.phase}
                />
                <KeyValue
                  label="Status"
                  value={razorpayPhase6FinalAuditLockReadiness.status}
                />
                <KeyValue
                  label="Latest completed"
                  value={
                    razorpayPhase6FinalAuditLockReadiness.latestCompletedPreviousPhase
                  }
                />
                <KeyValue
                  label="Next phase"
                  value={razorpayPhase6FinalAuditLockReadiness.nextPhase}
                />
                <KeyValue
                  label="Audit-lock flag"
                  value={
                    razorpayPhase6FinalAuditLockReadiness.razorpayPhase6FinalAuditLockEnabled
                      ? "Enabled"
                      : "Disabled"
                  }
                />
                <KeyValue label="Future controlled pilot by 6T" value="No" />
                <KeyValue label="Pilot execution" value="No" />
                <KeyValue label="Real business mutation" value="No" />
                <KeyValue label="Real Order mutation" value="No" />
                <KeyValue label="Real Payment mutation" value="No" />
                <KeyValue label="WhatsApp send" value="No" />
                <KeyValue label="WhatsApp queued" value="No" />
                <KeyValue label="Meta Cloud call" value="No" />
                <KeyValue label="Delhivery call" value="No" />
                <KeyValue label="Razorpay call" value="No" />
                <KeyValue label="Shipment created" value="No" />
                <KeyValue label="AWB created" value="No" />
                <KeyValue label="Customer notification" value="No" />
                <KeyValue label="Provider call" value="No" />
                <KeyValue
                  label="Locked records"
                  value={String(
                    razorpayPhase6FinalAuditLockReadiness.finalAuditLockCounts
                      .lockedForFutureControlledPilotReview,
                  )}
                />
              </div>

              <div className="px-6 pb-4 text-xs text-muted-foreground">
                <strong>Next action:</strong>{" "}
                {razorpayPhase6FinalAuditLockReadiness.nextAction}
              </div>

              <div
                className="px-6 pb-4"
                data-testid="phase6t-audit-chain-table"
              >
                <h4 className="text-sm font-semibold mb-2">
                  Audit chain attestation
                </h4>
                <div className="overflow-x-auto rounded border border-border">
                  <table className="w-full text-xs">
                    <thead className="bg-muted/40">
                      <tr className="text-left">
                        <th className="px-3 py-2">Phase</th>
                        <th className="px-3 py-2">Required status</th>
                        <th className="px-3 py-2">Actual status</th>
                        <th className="px-3 py-2">Verified</th>
                        <th className="px-3 py-2">Mutation</th>
                        <th className="px-3 py-2">Provider</th>
                        <th className="px-3 py-2">Notification</th>
                      </tr>
                    </thead>
                    <tbody>
                      {razorpayPhase6FinalAuditLockReadiness.auditChain.map(
                        (row) => (
                          <tr key={row.phase} className="border-t border-border">
                            <td className="px-3 py-2 font-mono">
                              Phase {row.phase}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.requiredStatus}
                            </td>
                            <td className="px-3 py-2 font-mono">
                              {row.actualStatus}
                            </td>
                            <td className="px-3 py-2">
                              {row.verified ? "Yes" : "No"}
                            </td>
                            <td className="px-3 py-2">No</td>
                            <td className="px-3 py-2">No</td>
                            <td className="px-3 py-2">No</td>
                          </tr>
                        ),
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="px-6 pb-4 grid gap-3 lg:grid-cols-2">
                <ContractList
                  title="Director signoff contract"
                  data={razorpayPhase6FinalAuditLockReadiness.directorSignoffContract}
                  testId="phase6t-director-signoff-contract"
                />
                <ContractList
                  title="Kill-switch contract"
                  data={razorpayPhase6FinalAuditLockReadiness.killSwitchContract}
                  testId="phase6t-kill-switch-contract"
                />
                <ContractList
                  title="Rollback contract"
                  data={razorpayPhase6FinalAuditLockReadiness.rollbackContract}
                  testId="phase6t-rollback-contract"
                />
                <ContractList
                  title="Safety invariants"
                  data={razorpayPhase6FinalAuditLockReadiness.safetyInvariants}
                  testId="phase6t-safety-invariants"
                />
              </div>

              <div className="px-6 pb-4 grid gap-3 lg:grid-cols-2">
                <div data-testid="phase6t-abort-criteria">
                  <h4 className="text-sm font-semibold mb-2">
                    Abort criteria
                  </h4>
                  <ul className="space-y-1 text-xs">
                    {razorpayPhase6FinalAuditLockReadiness.abortCriteria.map(
                      (item) => (
                        <li
                          key={`${item.if}-${item.then}`}
                          className="font-mono rounded border border-border bg-muted/20 px-2 py-1"
                        >
                          {item.if} - {item.then}
                        </li>
                      ),
                    )}
                  </ul>
                </div>
                <div data-testid="phase6t-operator-checklist">
                  <h4 className="text-sm font-semibold mb-2">
                    Operator checklist
                  </h4>
                  <ul className="space-y-1 text-xs">
                    {razorpayPhase6FinalAuditLockReadiness.operatorChecklist.map(
                      (item) => (
                        <li
                          key={`${item.step}-${item.surface}`}
                          className="font-mono rounded border border-border bg-muted/20 px-2 py-1"
                        >
                          {item.step} - {item.surface}
                        </li>
                      ),
                    )}
                  </ul>
                </div>
              </div>
            </>
          )}

          {razorpayPhase6FinalAuditLocks && (
            <div
              className="px-6 pb-4"
              data-testid="phase6t-lock-records-table"
            >
              <h4 className="text-sm font-semibold mb-2">
                Final audit lock records (
                {razorpayPhase6FinalAuditLocks.items.length})
              </h4>
              {razorpayPhase6FinalAuditLocks.items.length === 0 ? (
                <div className="rounded border border-dashed border-border bg-muted/30 px-4 py-3 text-xs text-muted-foreground">
                  No final audit lock records yet. Use the Phase 6T CLI
                  review commands after an eligible Phase 6S plan exists.
                </div>
              ) : (
                <div className="overflow-x-auto rounded border border-border">
                  <table className="w-full text-xs">
                    <thead className="bg-muted/40">
                      <tr className="text-left">
                        <th className="px-3 py-2">ID</th>
                        <th className="px-3 py-2">Event</th>
                        <th className="px-3 py-2">Status</th>
                        <th className="px-3 py-2">Chain</th>
                        <th className="px-3 py-2">Provider</th>
                      </tr>
                    </thead>
                    <tbody>
                      {razorpayPhase6FinalAuditLocks.items.map((row) => (
                        <tr key={row.id} className="border-t border-border">
                          <td className="px-3 py-2 font-mono">{row.id}</td>
                          <td className="px-3 py-2 font-mono">
                            {row.eventName}
                          </td>
                          <td className="px-3 py-2 font-mono">
                            {row.status}
                          </td>
                          <td className="px-3 py-2">
                            {row.fullChainVerified ? "Verified" : "Pending"}
                          </td>
                          <td className="px-3 py-2">No call</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          <div
            className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground"
            data-testid="phase6t-cli-only-reminder"
          >
            <strong>CLI-only review.</strong> Inspect Final Audit, Lock
            Audit Record Only, Decision Gate Only, Future Controlled
            Pilot Contract, Audit Chain Attestation, No Live Execution,
            No Provider Call.
          </div>
        </section>
      )}

      {(mcpReadiness || mcpSecurityPosture || mcpTools || mcpInvocations) && (
        <section
          className="mt-6 surface-card overflow-hidden"
          data-testid="mcp-gateway-section"
        >
          <div className="border-b border-border px-6 py-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
                <Network className="h-5 w-5 text-primary" />
                MCP Gateway Readiness
              </h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
                Phase 6M-0 — read-only foundation for the future
                Claude / ChatGPT / Codex MCP connector. MCP defaults
                are <strong>disabled / read-only</strong>; no write
                tools, no provider tools, no public endpoint, no raw
                secrets, no full PII.
              </p>
            </div>
            {mcpReadiness && (
              <StatusPill
                tone={
                  mcpReadiness.safeToStartPhase6M ? "success" : "warning"
                }
              >
                {mcpReadiness.mcpEnabled
                  ? "MCP enabled"
                  : "MCP disabled (safe)"}
              </StatusPill>
            )}
          </div>
          {mcpReadiness && (
            <McpReadinessCard readiness={mcpReadiness} />
          )}
          {mcpSecurityPosture && (
            <McpSecurityPostureCard posture={mcpSecurityPosture} />
          )}
          {mcpTools && <McpToolsTable response={mcpTools} />}
          {mcpInvocations && (
            <McpInvocationsTable response={mcpInvocations} />
          )}
          <div className="border-t border-border bg-muted/20 px-6 py-3 text-xs text-muted-foreground">
            <strong>Read-only.</strong> No "Run Tool" / "Send" / "Execute"
            buttons exist on this page. Even the simulator runs only
            the registered read-only tools through the Phase 6M-0
            executor (no provider call, no business mutation).
          </div>
        </section>
      )}

      <section className="mt-6 grid gap-4 lg:grid-cols-2">
        <Panel title="Blockers & Warnings" icon={ShieldCheck}>
          <IssueList items={overview.blockers} empty="No blockers" />
          <IssueList items={overview.warnings} empty="No warnings" />
        </Panel>
        <Panel title="Audit Timeline" icon={CheckCircle2}>
          {overview.auditTimeline.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No SaaS admin audit events yet.
            </p>
          ) : (
            <div className="space-y-3">
              {overview.auditTimeline.map((event) => (
                <div
                  key={event.id}
                  className="rounded-md border border-border bg-muted/20 p-3"
                >
                  <div className="text-sm font-medium">{event.text}</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {event.kind} - {new Date(event.createdAt).toLocaleString()}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </section>
    </>
  );
}

function Phase6OReviewRow({
  row,
  pending,
  onAction,
}: {
  row: SaasRazorpaySandboxStatusReviewDto;
  pending: boolean;
  onAction: (
    action: "approve" | "reject" | "archive",
    reason: string,
  ) => Promise<void>;
}) {
  const finalised =
    row.status === "approved_for_future_phase6p" ||
    row.status === "rejected" ||
    row.status === "archived" ||
    row.status === "blocked";
  return (
    <tr className="border-t border-border align-top">
      <td className="py-1 pr-3">{row.id}</td>
      <td className="py-1 pr-3 font-mono">{row.eventName}</td>
      <td className="py-1 pr-3 font-mono">{row.sourceEventId}</td>
      <td className="py-1 pr-3">{row.proposedPaymentStatus}</td>
      <td className="py-1 pr-3">{row.proposedOrderEffect}</td>
      <td className="py-1 pr-3">
        <StatusPill
          tone={
            row.status === "approved_for_future_phase6p"
              ? "success"
              : row.status === "rejected" || row.status === "blocked"
              ? "danger"
              : row.status === "archived"
              ? "neutral"
              : "info"
          }
        >
          {row.status}
        </StatusPill>
      </td>
      <td className="py-1 pr-3 text-emerald-600 font-medium">Disabled</td>
      <td className="py-1 pr-3">
        <div className="flex flex-wrap gap-1">
          <button
            type="button"
            disabled={pending || finalised}
            className="rounded border border-emerald-600/40 bg-emerald-600/5 px-2 py-0.5 text-[11px] font-medium disabled:opacity-50"
            onClick={() => onAction("approve", "")}
            data-testid={`phase6o-review-${row.id}-approve`}
          >
            Approve Review Only
          </button>
          <button
            type="button"
            disabled={pending || finalised}
            className="rounded border border-amber-600/40 bg-amber-600/5 px-2 py-0.5 text-[11px] font-medium disabled:opacity-50"
            onClick={() => onAction("reject", "")}
            data-testid={`phase6o-review-${row.id}-reject`}
          >
            Reject Review
          </button>
          <button
            type="button"
            disabled={pending || row.status === "archived"}
            className="rounded border border-border bg-muted/30 px-2 py-0.5 text-[11px] font-medium disabled:opacity-50"
            onClick={() => onAction("archive", "")}
            data-testid={`phase6o-review-${row.id}-archive`}
          >
            Archive Review
          </button>
        </div>
      </td>
    </tr>
  );
}


function MetricCard({
  icon: Icon,
  label,
  value,
  detail,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="surface-card p-4">
      <div className="flex items-center gap-2 text-xs uppercase text-muted-foreground">
        <Icon className="h-4 w-4" />
        {label}
      </div>
      <div className="mt-2 truncate text-xl font-semibold">{value}</div>
      <div className="mt-1 text-sm text-muted-foreground">{detail}</div>
    </div>
  );
}

function Panel({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon: LucideIcon;
  children: ReactNode;
}) {
  return (
    <div className="surface-card p-5">
      <h3 className="mb-4 flex items-center gap-2 font-display text-lg font-semibold">
        <Icon className="h-5 w-5 text-primary" />
        {title}
      </h3>
      <div className="space-y-3">{children}</div>
    </div>
  );
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  );
}

function ContractList({
  title,
  data,
  testId,
}: {
  title: string;
  data: Record<string, unknown>;
  testId: string;
}) {
  return (
    <div data-testid={testId}>
      <h4 className="text-sm font-semibold mb-2">{title}</h4>
      <div className="rounded border border-border bg-muted/20 p-3 text-xs">
        {Object.entries(data).map(([key, value]) => (
          <div key={key} className="mb-2 last:mb-0">
            <div className="font-mono text-[11px] text-muted-foreground">
              {key}
            </div>
            <div className="mt-0.5 break-words">
              {Array.isArray(value)
                ? value.join(", ")
                : typeof value === "object" && value !== null
                  ? JSON.stringify(value)
                  : String(value)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function IssueList({ items, empty }: { items: string[]; empty: string }) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">{empty}</p>;
  }
  return (
    <ul className="space-y-2 text-sm">
      {items.map((item) => (
        <li key={item} className="rounded-md border border-border p-2">
          {item}
        </li>
      ))}
    </ul>
  );
}

function LockRow({ label, safe }: { label: string; safe: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-sm">{label}</span>
      <StatusPill tone={safe ? "success" : "danger"}>
        {safe ? "Locked" : "Open"}
      </StatusPill>
    </div>
  );
}

function ProviderRow({ provider }: { provider: SaasProviderReadiness }) {
  return (
    <tr className="border-t border-border/60">
      <td className="px-6 py-3 font-medium">{provider.providerLabel}</td>
      <td className="py-3">
        <StatusPill tone={toneForStatus(provider.status)}>
          {provider.status}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={provider.secretRefsPresent ? "success" : "warning"}>
          {provider.secretRefsPresent ? "Present" : "Missing"}
        </StatusPill>
      </td>
      <td className="py-3">{provider.validationStatus}</td>
      <td className="px-6 py-3">
        <StatusPill tone="neutral">Env/config</StatusPill>
      </td>
    </tr>
  );
}

function RuntimeOperationRow({
  decision,
}: {
  decision: SaasRuntimeDryRunOperationDecision;
}) {
  return (
    <tr
      className="border-t border-border/60"
      data-testid="runtime-operation-row"
    >
      <td className="px-6 py-3 font-mono text-xs">
        {decision.operationType}
      </td>
      <td className="py-3">{decision.providerLabel}</td>
      <td className="py-3">
        <StatusPill
          tone={
            decision.sideEffectRisk === "high"
              ? "warning"
              : decision.sideEffectRisk === "medium"
                ? "warning"
                : "neutral"
          }
        >
          {decision.sideEffectRisk}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill
          tone={decision.providerSettingExists ? "success" : "warning"}
        >
          {decision.providerSettingExists ? "Configured" : "Missing"}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={decision.dryRun ? "success" : "danger"}>
          true
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone="neutral">false</StatusPill>
      </td>
      <td className="px-6 py-3 text-xs text-muted-foreground">
        {decision.nextAction}
      </td>
    </tr>
  );
}

function LiveGatePolicyRow({ policy }: { policy: SaasLiveGatePolicy }) {
  const decision = policy.currentGateDecision ?? "blocked_by_default";
  return (
    <tr className="border-t border-border/60" data-testid="live-gate-policy-row">
      <td className="px-6 py-3 font-mono text-xs">{policy.operationType}</td>
      <td className="py-3">{policy.providerType}</td>
      <td className="py-3">
        <StatusPill
          tone={
            policy.riskLevel === "critical" || policy.riskLevel === "high"
              ? "warning"
              : "neutral"
          }
        >
          {policy.riskLevel}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={policy.approvalRequired ? "warning" : "neutral"}>
          {policy.approvalRequired ? "Required" : "No"}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={policy.caioReviewRequired ? "warning" : "neutral"}>
          {policy.caioReviewRequired ? "Required" : "No"}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={policy.consentRequired ? "warning" : "neutral"}>
          {policy.consentRequired ? "Required" : "No"}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={policy.claimVaultRequired ? "warning" : "neutral"}>
          {policy.claimVaultRequired ? "Required" : "No"}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={policy.webhookRequired ? "warning" : "neutral"}>
          {policy.webhookRequired ? "Required" : "No"}
        </StatusPill>
      </td>
      <td className="py-3 text-xs text-muted-foreground">{decision}</td>
      <td className="px-6 py-3">
        <StatusPill tone="neutral">
          {policy.liveAllowedNow ? "true" : "false"}
        </StatusPill>
      </td>
    </tr>
  );
}

function LiveGateSimulationRow({
  simulation,
}: {
  simulation: SaasRuntimeLiveGateSimulation;
}) {
  return (
    <tr
      className="border-t border-border/60"
      data-testid="live-gate-simulation-row"
    >
      <td className="px-6 py-3 font-mono text-xs">
        {simulation.operationType}
      </td>
      <td className="py-3">{simulation.providerType}</td>
      <td className="py-3">
        <StatusPill tone={toneForStatus(simulation.status)}>
          {simulation.status}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={toneForStatus(simulation.approvalStatus)}>
          {simulation.approvalStatus}
        </StatusPill>
      </td>
      <td className="py-3 text-xs text-muted-foreground">
        {simulation.gateDecision}
      </td>
      <td className="px-6 py-3">
        <StatusPill tone="success">
          {simulation.providerCallAttempted ? "attempted" : "not attempted"}
        </StatusPill>
      </td>
    </tr>
  );
}

function AiTaskRow({ task }: { task: SaasAiProviderRoutePreview }) {
  return (
    <tr className="border-t border-border/60" data-testid="ai-task-row">
      <td className="px-6 py-3 font-mono text-xs">{task.taskType}</td>
      <td className="py-3 text-xs">
        {task.primaryProvider} / {task.primaryModel}
      </td>
      <td className="py-3 text-xs">
        {task.fallbackProvider} / {task.fallbackModel}
      </td>
      <td className="py-3 text-xs">
        {task.maxTokens}{" "}
        <span className="text-muted-foreground">
          ({task.maxTokensFromEnv ? "env" : "default"})
        </span>
      </td>
      <td className="py-3">
        <StatusPill tone={task.safetyWrappersRequired ? "warning" : "neutral"}>
          {task.safetyWrappersRequired ? "Wrappers required" : "Internal only"}
        </StatusPill>
      </td>
      <td className="px-6 py-3 text-xs text-muted-foreground">
        {task.nextAction}
      </td>
    </tr>
  );
}

function RuntimeProviderRow({
  provider,
}: {
  provider: SaasRuntimeRoutingProviderPreview;
}) {
  const refsResolvable =
    provider.secretRefsPresent &&
    !provider.secretRefsResolvablePreview.anyMissingEnv;
  return (
    <tr className="border-t border-border/60" data-testid="runtime-provider-row">
      <td className="px-6 py-3 font-medium">{provider.providerLabel}</td>
      <td className="py-3">
        <StatusPill
          tone={provider.integrationSettingExists ? "success" : "warning"}
        >
          {provider.integrationSettingExists ? "Configured" : "Missing"}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={toneForStatus(provider.settingStatus)}>
          {provider.settingStatus}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={provider.secretRefsPresent ? "success" : "warning"}>
          {provider.secretRefsPresent
            ? `${provider.expectedSecretRefKeys.length - provider.missingSecretRefs.length}/${provider.expectedSecretRefKeys.length} present`
            : "Missing"}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={refsResolvable ? "success" : "warning"}>
          {refsResolvable ? "Resolvable" : "Preview blocked"}
        </StatusPill>
      </td>
      <td className="px-6 py-3">
        <StatusPill tone="neutral">{provider.runtimeSource}</StatusPill>
      </td>
    </tr>
  );
}

function ProviderTestPlanInvariants({
  plan,
}: {
  plan: SaasProviderTestPlan | null;
}) {
  const rows: Array<{ label: string; value: boolean; safeWhenFalse?: boolean }> =
    plan
      ? [
          { label: "dryRun", value: plan.dryRun },
          {
            label: "providerCallAllowed",
            value: plan.providerCallAllowed,
            safeWhenFalse: true,
          },
          {
            label: "externalCallWillBeMade",
            value: plan.externalCallWillBeMade,
            safeWhenFalse: true,
          },
          {
            label: "externalCallWasMade",
            value: plan.externalCallWasMade,
            safeWhenFalse: true,
          },
          {
            label: "providerCallAttempted",
            value: plan.providerCallAttempted,
            safeWhenFalse: true,
          },
          { label: "realMoney", value: plan.realMoney, safeWhenFalse: true },
          {
            label: "realCustomerDataAllowed",
            value: plan.realCustomerDataAllowed,
            safeWhenFalse: true,
          },
        ]
      : [];
  return (
    <div className="rounded-md border border-border bg-muted/20 p-3">
      <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <ShieldCheck className="h-4 w-4 text-primary" />
        Safety invariants
      </h4>
      {plan === null ? (
        <p className="text-xs text-muted-foreground">
          No plan prepared yet.
        </p>
      ) : (
        <div className="space-y-1.5">
          {rows.map((row) => {
            const safe =
              row.safeWhenFalse === true ? row.value === false : row.value;
            return (
              <div
                key={row.label}
                className="flex items-center justify-between text-xs"
              >
                <span className="font-mono text-muted-foreground">
                  {row.label}
                </span>
                <StatusPill tone={safe ? "success" : "danger"}>
                  {String(row.value)}
                </StatusPill>
              </div>
            );
          })}
          <div className="pt-1 text-[11px] text-muted-foreground">
            amount: {plan.amountPaise ?? "n/a"} paise · {plan.currency} ·
            payloadHash: {plan.payloadHash ? "present" : "missing"}
          </div>
        </div>
      )}
    </div>
  );
}

function ProviderTestPlanEnvReadiness({
  plan,
}: {
  plan: SaasProviderTestPlan | null;
}) {
  const env = plan?.envReadiness;
  return (
    <div className="rounded-md border border-border bg-muted/20 p-3">
      <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <KeyRound className="h-4 w-4 text-primary" />
        Razorpay env readiness
      </h4>
      {env === undefined ? (
        <p className="text-xs text-muted-foreground">
          No plan prepared yet.
        </p>
      ) : (
        <div className="space-y-1.5">
          <EnvRow
            label="Razorpay key id"
            present={!!env.envPresence?.RAZORPAY_KEY_ID}
            blockingWhenMissing
          />
          <EnvRow
            label="Razorpay key secret"
            present={!!env.envPresence?.RAZORPAY_KEY_SECRET}
            blockingWhenMissing
          />
          <EnvRow
            label="Razorpay webhook secret"
            present={!!env.envPresence?.RAZORPAY_WEBHOOK_SECRET}
          />
          <div className="pt-1 text-[11px] text-muted-foreground">
            Masked refs only — raw values are never returned.
          </div>
        </div>
      )}
    </div>
  );
}

function EnvRow({
  label,
  present,
  blockingWhenMissing = false,
}: {
  label: string;
  present: boolean;
  blockingWhenMissing?: boolean;
}) {
  const tone: "success" | "warning" | "danger" = present
    ? "success"
    : blockingWhenMissing
      ? "danger"
      : "warning";
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="font-mono text-muted-foreground">{label}</span>
      <StatusPill tone={tone}>
        {present ? "present" : "missing"}
      </StatusPill>
    </div>
  );
}


function ProviderExecutionEnvCard({
  env,
}: {
  env: SaasProviderExecutionReadiness["envReadiness"];
}) {
  const keyTone: "success" | "warning" | "danger" = env.isLiveKey
    ? "danger"
    : env.isTestKey
      ? "success"
      : "warning";
  return (
    <div className="rounded-md border border-border bg-muted/20 p-3">
      <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <KeyRound className="h-4 w-4 text-primary" />
        Razorpay execution-gate env
      </h4>
      <div className="space-y-1.5 text-xs">
        <div className="flex items-center justify-between">
          <span className="font-mono text-muted-foreground">
            Phase 6K env flag
          </span>
          <StatusPill tone={env.envFlagEnabled ? "success" : "warning"}>
            {env.envFlagEnabled ? "enabled" : "disabled"}
          </StatusPill>
        </div>
        <div className="flex items-center justify-between">
          <span className="font-mono text-muted-foreground">
            Razorpay key mode
          </span>
          <StatusPill tone={keyTone}>{env.razorpayKeyMode}</StatusPill>
        </div>
        <div className="flex items-center justify-between">
          <span className="font-mono text-muted-foreground">
            Key id (masked)
          </span>
          <span className="font-mono text-[11px]">
            {env.razorpayKeyIdMasked || "missing"}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="font-mono text-muted-foreground">
            Key secret
          </span>
          <StatusPill
            tone={env.razorpayKeySecretPresent ? "success" : "danger"}
          >
            {env.razorpayKeySecretPresent ? "present" : "missing"}
          </StatusPill>
        </div>
        <div className="flex items-center justify-between">
          <span className="font-mono text-muted-foreground">
            Webhook secret
          </span>
          <StatusPill
            tone={env.razorpayWebhookSecretPresent ? "success" : "warning"}
          >
            {env.razorpayWebhookSecretPresent ? "present" : "missing"}
          </StatusPill>
        </div>
      </div>
      <div className="pt-2 text-[11px] text-muted-foreground">
        Masked refs only. Raw secrets are never exposed.
      </div>
    </div>
  );
}

function ProviderExecutionInvariants({
  attempt,
}: {
  attempt: SaasProviderExecutionAttempt | null;
}) {
  const rows: Array<{ label: string; value: boolean; safeWhenFalse?: boolean }> =
    attempt
      ? [
          { label: "testMode", value: attempt.testMode },
          {
            label: "realMoney",
            value: attempt.realMoney,
            safeWhenFalse: true,
          },
          {
            label: "realCustomerDataAllowed",
            value: attempt.realCustomerDataAllowed,
            safeWhenFalse: true,
          },
          {
            label: "businessMutationWasMade",
            value: attempt.businessMutationWasMade,
            safeWhenFalse: true,
          },
          {
            label: "paymentLinkCreated",
            value: attempt.paymentLinkCreated,
            safeWhenFalse: true,
          },
          {
            label: "paymentCaptured",
            value: attempt.paymentCaptured,
            safeWhenFalse: true,
          },
          {
            label: "customerNotificationSent",
            value: attempt.customerNotificationSent,
            safeWhenFalse: true,
          },
        ]
      : [];
  return (
    <div className="rounded-md border border-border bg-muted/20 p-3">
      <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <ShieldCheck className="h-4 w-4 text-primary" />
        Latest attempt safety invariants
      </h4>
      {attempt === null ? (
        <p className="text-xs text-muted-foreground">
          No execution attempt yet.
        </p>
      ) : (
        <div className="space-y-1.5">
          {rows.map((row) => {
            const safe =
              row.safeWhenFalse === true ? row.value === false : row.value;
            return (
              <div
                key={row.label}
                className="flex items-center justify-between text-xs"
              >
                <span className="font-mono text-muted-foreground">
                  {row.label}
                </span>
                <StatusPill tone={safe ? "success" : "danger"}>
                  {String(row.value)}
                </StatusPill>
              </div>
            );
          })}
          <div className="pt-1 text-[11px] text-muted-foreground">
            providerObjectId:{" "}
            <span className="font-mono">
              {attempt.providerObjectId || "n/a"}
            </span>{" "}
            · status: {attempt.providerStatus || attempt.status}
          </div>
        </div>
      )}
    </div>
  );
}

function ProviderExecutionAttemptsTable({
  attempts,
}: {
  attempts: SaasProviderExecutionAttempt[];
}) {
  if (!attempts.length) {
    return (
      <div className="border-t border-border px-6 py-3 text-xs text-muted-foreground">
        No execution attempts recorded yet.
      </div>
    );
  }
  return (
    <div className="overflow-x-auto border-t border-border">
      <table className="w-full min-w-[860px] text-sm">
        <thead className="bg-muted/30 text-[11px] uppercase text-muted-foreground">
          <tr>
            <th className="px-6 py-3 text-left font-medium">Execution</th>
            <th className="py-3 text-left font-medium">Status</th>
            <th className="py-3 text-left font-medium">
              Provider obj id
            </th>
            <th className="py-3 text-left font-medium">Provider call</th>
            <th className="py-3 text-left font-medium">External call</th>
            <th className="py-3 text-left font-medium">Mutation</th>
            <th className="py-3 text-left font-medium">Payment captured</th>
            <th className="px-6 py-3 text-left font-medium">Notify sent</th>
          </tr>
        </thead>
        <tbody>
          {attempts.map((attempt) => (
            <tr
              key={attempt.executionId}
              className="border-t border-border/60"
              data-testid="provider-execution-attempt-row"
            >
              <td className="px-6 py-3 font-mono text-xs">
                {attempt.executionId}
              </td>
              <td className="py-3">
                <StatusPill tone={toneForStatus(attempt.status)}>
                  {attempt.status}
                </StatusPill>
              </td>
              <td className="py-3 text-xs font-mono">
                {attempt.providerObjectId || "—"}
              </td>
              <td className="py-3">
                <StatusPill
                  tone={
                    attempt.providerCallAttempted ? "warning" : "success"
                  }
                >
                  {String(attempt.providerCallAttempted)}
                </StatusPill>
              </td>
              <td className="py-3">
                <StatusPill
                  tone={
                    attempt.externalCallWasMade ? "warning" : "success"
                  }
                >
                  {String(attempt.externalCallWasMade)}
                </StatusPill>
              </td>
              <td className="py-3">
                <StatusPill
                  tone={
                    attempt.businessMutationWasMade ? "danger" : "success"
                  }
                >
                  {String(attempt.businessMutationWasMade)}
                </StatusPill>
              </td>
              <td className="py-3">
                <StatusPill
                  tone={attempt.paymentCaptured ? "danger" : "success"}
                >
                  {String(attempt.paymentCaptured)}
                </StatusPill>
              </td>
              <td className="px-6 py-3">
                <StatusPill
                  tone={
                    attempt.customerNotificationSent ? "danger" : "success"
                  }
                >
                  {String(attempt.customerNotificationSent)}
                </StatusPill>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}


function RazorpayAuditReviewCard({
  review,
}: {
  review: SaasRazorpayAuditReview;
}) {
  return (
    <div className="border-t border-border px-6 py-4">
      <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <ShieldCheck className="h-4 w-4 text-primary" />
        Phase 6K execution audit
      </h4>
      <div className="grid gap-3 sm:grid-cols-4">
        <KeyValue label="Execution" value={review.executionId} />
        <KeyValue
          label="Provider order id"
          value={review.providerObjectId ?? "n/a"}
        />
        <KeyValue label="Status" value={review.status ?? "n/a"} />
        <KeyValue
          label="Rollback"
          value={review.rollbackStatus ?? "n/a"}
        />
      </div>
      {review.invariantResults && review.invariantResults.length > 0 && (
        <div className="mt-4 grid gap-1.5">
          {review.invariantResults.map((inv) => (
            <div
              key={inv.key}
              className="flex items-center justify-between text-xs"
              data-testid="razorpay-audit-invariant-row"
            >
              <span className="font-mono text-muted-foreground">
                {inv.key}
              </span>
              <StatusPill tone={inv.passed ? "success" : "danger"}>
                {String(inv.actual)}
              </StatusPill>
            </div>
          ))}
        </div>
      )}
      <div className="mt-3 text-[11px] text-muted-foreground">
        Audit events: {review.auditEventCount ?? 0} ·
        rawSecretLeakDetected:{" "}
        <span className="font-mono">
          {String(Boolean(review.rawSecretLeakDetected))}
        </span>
      </div>
      {review.blockers && review.blockers.length > 0 && (
        <IssueList items={review.blockers} empty="No blockers" />
      )}
    </div>
  );
}

function RazorpayWebhookReadinessCard({
  readiness,
}: {
  readiness: SaasRazorpayWebhookReadiness;
}) {
  const keyTone: "success" | "warning" | "danger" = readiness.isLiveKey
    ? "danger"
    : readiness.isTestKey
      ? "success"
      : "warning";
  return (
    <div className="border-t border-border px-6 py-4">
      <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <Webhook className="h-4 w-4 text-primary" />
        Webhook readiness
      </h4>
      <div className="grid gap-3 sm:grid-cols-4">
        <KeyValue label="Key mode" value={readiness.razorpayKeyMode} />
        <KeyValue
          label="Key id (masked)"
          value={readiness.razorpayKeyIdMasked || "missing"}
        />
        <KeyValue
          label="Webhook secret"
          value={
            readiness.razorpayWebhookSecretPresent ? "present" : "missing"
          }
        />
        <KeyValue
          label="Latest succeeded"
          value={readiness.latestSucceededProviderObjectId ?? "n/a"}
        />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
        <StatusPill tone={keyTone}>
          {readiness.isTestKey ? "test mode" : readiness.razorpayKeyMode}
        </StatusPill>
        <StatusPill
          tone={
            readiness.safeToPlanWebhookReadiness ? "success" : "warning"
          }
        >
          {readiness.safeToPlanWebhookReadiness
            ? "Safe to plan"
            : "Plan blocked"}
        </StatusPill>
        <span className="text-muted-foreground">
          Phase 6K succeeded:{" "}
          <span className="font-mono">
            {readiness.phase6KSucceededExecutionCount}
          </span>
        </span>
      </div>
      {readiness.blockers && readiness.blockers.length > 0 && (
        <IssueList items={readiness.blockers} empty="No blockers" />
      )}
    </div>
  );
}

function RazorpayWebhookPlanCard({
  plan,
}: {
  plan: SaasRazorpayWebhookPlan;
}) {
  return (
    <div className="border-t border-border px-6 py-4">
      <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <ClipboardList className="h-4 w-4 text-primary" />
        Webhook readiness plan ({plan.policyVersion})
      </h4>
      <div className="grid gap-3 sm:grid-cols-3">
        <KeyValue
          label="Endpoint"
          value={`${plan.endpointDesign.method} ${plan.endpointDesign.path}`}
        />
        <KeyValue
          label="Signature"
          value={`${plan.signatureVerificationDesign.algorithm} on ${plan.signatureVerificationDesign.header}`}
        />
        <KeyValue
          label="Replay window"
          value={`${plan.replayProtection.windowSeconds}s`}
        />
        <KeyValue
          label="Idempotency key"
          value={plan.idempotencyDesign.key}
        />
        <KeyValue
          label="Allowlist size"
          value={String(plan.eventAllowlist.length)}
        />
        <KeyValue
          label="Denylist size"
          value={String(plan.eventDenylist.length)}
        />
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <div className="rounded-md border border-border bg-muted/20 p-3 text-xs">
          <div className="mb-1 font-semibold text-muted-foreground">
            Allowlist
          </div>
          <ul className="space-y-1 font-mono text-[11px]">
            {plan.eventAllowlist.map((event) => (
              <li
                key={event}
                data-testid="razorpay-webhook-allowlist-row"
              >
                {event}
              </li>
            ))}
          </ul>
        </div>
        <div className="rounded-md border border-border bg-muted/20 p-3 text-xs">
          <div className="mb-1 font-semibold text-muted-foreground">
            Denylist
          </div>
          <ul className="space-y-1 font-mono text-[11px]">
            {plan.eventDenylist.map((event) => (
              <li
                key={event}
                data-testid="razorpay-webhook-denylist-row"
              >
                {event}
              </li>
            ))}
          </ul>
        </div>
      </div>
      <div className="mt-3 grid gap-1.5 text-xs">
        <div className="flex items-center justify-between">
          <span className="font-mono text-muted-foreground">
            Phase 6L mutation policy
          </span>
          <StatusPill tone="success">
            no order/payment/shipment/notify mutations
          </StatusPill>
        </div>
        <div className="flex items-center justify-between">
          <span className="font-mono text-muted-foreground">
            Phase 6L registers webhook
          </span>
          <StatusPill tone="success">
            {String(plan.endpointDesign.phase6LRegistration)}
          </StatusPill>
        </div>
        <div className="flex items-center justify-between">
          <span className="font-mono text-muted-foreground">
            Sensitive payload keys scrubbed
          </span>
          <span className="font-mono text-[11px]">
            {plan.auditLoggingPlan.payloadHandling.sensitiveKeysToScrub.length}
          </span>
        </div>
      </div>
      <div className="mt-3 text-[11px] text-muted-foreground">
        Next action:{" "}
        <span className="font-medium">{plan.nextAction}</span> · Next
        phase: {plan.nextPhase}
      </div>
    </div>
  );
}


function McpReadinessCard({
  readiness,
}: {
  readiness: McpGatewayReadiness;
}) {
  return (
    <div className="border-t border-border px-6 py-4">
      <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <Bot className="h-4 w-4 text-primary" />
        MCP mode
      </h4>
      <div className="grid gap-3 sm:grid-cols-4">
        <KeyValue label="MCP_ENABLED" value={String(readiness.mcpEnabled)} />
        <KeyValue label="Read-only mode" value={String(readiness.readOnlyMode)} />
        <KeyValue label="Write tools" value={String(readiness.writeToolsEnabled)} />
        <KeyValue
          label="Provider tools"
          value={String(readiness.providerToolsEnabled)}
        />
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-4 text-xs">
        <KeyValue label="Tools" value={String(readiness.toolCount)} />
        <KeyValue label="Resources" value={String(readiness.resourceCount)} />
        <KeyValue label="Prompts" value={String(readiness.promptCount)} />
        <KeyValue
          label="Active clients"
          value={String(readiness.activeClientCount)}
        />
      </div>
      <div className="mt-3 text-[11px] text-muted-foreground">
        Next action:{" "}
        <span className="font-medium">{readiness.nextAction}</span>
      </div>
    </div>
  );
}

function McpSecurityPostureCard({
  posture,
}: {
  posture: McpSecurityPosture;
}) {
  const rows: Array<{ label: string; value: boolean; safeWhenFalse?: boolean }> = [
    { label: "authRequired", value: posture.authRequired },
    {
      label: "writeToolsEnabled",
      value: posture.writeToolsEnabled,
      safeWhenFalse: true,
    },
    {
      label: "providerToolsEnabled",
      value: posture.providerToolsEnabled,
      safeWhenFalse: true,
    },
    {
      label: "forbiddenToolsRegistered",
      value: posture.forbiddenToolsRegistered,
      safeWhenFalse: true,
    },
  ];
  const numericRows: Array<{ label: string; value: number }> = [
    { label: "rawSecretExposureCount", value: posture.rawSecretExposureCount },
    { label: "piiExposureCount", value: posture.piiExposureCount },
    {
      label: "providerCallAttemptedCount",
      value: posture.providerCallAttemptedCount,
    },
    {
      label: "businessMutationAttemptedCount",
      value: posture.businessMutationAttemptedCount,
    },
  ];
  return (
    <div className="border-t border-border px-6 py-4">
      <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <ShieldCheck className="h-4 w-4 text-primary" />
        Security posture
      </h4>
      <div className="grid gap-3 lg:grid-cols-2">
        <div className="rounded-md border border-border bg-muted/20 p-3">
          <div className="mb-1 text-xs font-semibold text-muted-foreground">
            Boolean invariants
          </div>
          <div className="space-y-1.5">
            {rows.map((row) => {
              const safe =
                row.safeWhenFalse === true ? row.value === false : row.value;
              return (
                <div
                  key={row.label}
                  className="flex items-center justify-between text-xs"
                >
                  <span className="font-mono text-muted-foreground">
                    {row.label}
                  </span>
                  <StatusPill tone={safe ? "success" : "danger"}>
                    {String(row.value)}
                  </StatusPill>
                </div>
              );
            })}
          </div>
        </div>
        <div className="rounded-md border border-border bg-muted/20 p-3">
          <div className="mb-1 text-xs font-semibold text-muted-foreground">
            Counters (must stay 0)
          </div>
          <div className="space-y-1.5">
            {numericRows.map((row) => (
              <div
                key={row.label}
                className="flex items-center justify-between text-xs"
              >
                <span className="font-mono text-muted-foreground">
                  {row.label}
                </span>
                <StatusPill tone={row.value === 0 ? "success" : "danger"}>
                  {row.value}
                </StatusPill>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function McpToolsTable({ response }: { response: McpToolsResponse }) {
  if (!response.tools.length) {
    return (
      <div className="border-t border-border px-6 py-3 text-xs text-muted-foreground">
        No MCP tools registered. Run{" "}
        <code>manage.py ensure_mcp_defaults</code>.
      </div>
    );
  }
  return (
    <div className="overflow-x-auto border-t border-border">
      <table className="w-full min-w-[920px] text-sm">
        <thead className="bg-muted/30 text-[11px] uppercase text-muted-foreground">
          <tr>
            <th className="px-6 py-3 text-left font-medium">Name</th>
            <th className="py-3 text-left font-medium">Category</th>
            <th className="py-3 text-left font-medium">Risk</th>
            <th className="py-3 text-left font-medium">Read-only</th>
            <th className="py-3 text-left font-medium">Provider call</th>
            <th className="py-3 text-left font-medium">Mutation</th>
            <th className="px-6 py-3 text-left font-medium">Scopes</th>
          </tr>
        </thead>
        <tbody>
          {response.tools.map((tool) => (
            <McpToolRow key={tool.name} tool={tool} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function McpToolRow({ tool }: { tool: McpToolDefinitionDto }) {
  const riskTone: "success" | "warning" | "danger" =
    tool.riskLevel === "low"
      ? "success"
      : tool.riskLevel === "critical" || tool.riskLevel === "high"
        ? "warning"
        : "neutral";
  return (
    <tr className="border-t border-border/60" data-testid="mcp-tool-row">
      <td className="px-6 py-3 font-mono text-xs">{tool.name}</td>
      <td className="py-3 text-xs">{tool.category}</td>
      <td className="py-3">
        <StatusPill tone={riskTone}>{tool.riskLevel}</StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={tool.readOnly ? "success" : "danger"}>
          {String(tool.readOnly)}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill
          tone={tool.providerCallAllowed ? "danger" : "success"}
        >
          {String(tool.providerCallAllowed)}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill
          tone={tool.businessMutationAllowed ? "danger" : "success"}
        >
          {String(tool.businessMutationAllowed)}
        </StatusPill>
      </td>
      <td className="px-6 py-3 text-[11px] font-mono text-muted-foreground">
        {tool.requiredScopes.join(", ")}
      </td>
    </tr>
  );
}

function McpInvocationsTable({
  response,
}: {
  response: McpInvocationsResponse;
}) {
  if (!response.invocations.length) {
    return (
      <div className="border-t border-border px-6 py-3 text-xs text-muted-foreground">
        No MCP invocations recorded yet.
      </div>
    );
  }
  return (
    <div className="overflow-x-auto border-t border-border">
      <table className="w-full min-w-[860px] text-sm">
        <thead className="bg-muted/30 text-[11px] uppercase text-muted-foreground">
          <tr>
            <th className="px-6 py-3 text-left font-medium">Invocation</th>
            <th className="py-3 text-left font-medium">Tool</th>
            <th className="py-3 text-left font-medium">Status</th>
            <th className="py-3 text-left font-medium">Provider call</th>
            <th className="py-3 text-left font-medium">Mutation</th>
            <th className="px-6 py-3 text-left font-medium">Created</th>
          </tr>
        </thead>
        <tbody>
          {response.invocations.map((row) => (
            <McpInvocationRow key={row.invocationId} row={row} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function McpInvocationRow({ row }: { row: McpToolInvocationDto }) {
  return (
    <tr
      className="border-t border-border/60"
      data-testid="mcp-invocation-row"
    >
      <td className="px-6 py-3 font-mono text-xs">{row.invocationId}</td>
      <td className="py-3 text-xs">{row.toolName}</td>
      <td className="py-3">
        <StatusPill tone={toneForStatus(row.status)}>{row.status}</StatusPill>
      </td>
      <td className="py-3">
        <StatusPill tone={row.providerCallAttempted ? "danger" : "success"}>
          {String(row.providerCallAttempted)}
        </StatusPill>
      </td>
      <td className="py-3">
        <StatusPill
          tone={row.businessMutationAttempted ? "danger" : "success"}
        >
          {String(row.businessMutationAttempted)}
        </StatusPill>
      </td>
      <td className="px-6 py-3 text-[11px] text-muted-foreground">
        {row.createdAt}
      </td>
    </tr>
  );
}


function RazorpayWebhookHandlerReadinessCard({
  readiness,
}: {
  readiness: SaasRazorpayWebhookHandlerReadiness;
}) {
  return (
    <div className="border-t border-border px-6 py-4">
      <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <Webhook className="h-4 w-4 text-primary" />
        Handler readiness
      </h4>
      <div className="grid gap-3 sm:grid-cols-4">
        <KeyValue
          label="Test mode enabled"
          value={String(readiness.webhookTestModeEnabled)}
        />
        <KeyValue
          label="Webhook secret"
          value={
            readiness.webhookSecretPresent ? "present" : "missing"
          }
        />
        <KeyValue
          label="Replay window"
          value={`${readiness.replayWindowSeconds}s`}
        />
        <KeyValue
          label="Allowed events"
          value={String(readiness.allowedEvents.length)}
        />
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <div className="rounded-md border border-border bg-muted/20 p-3 text-xs">
          <div className="mb-2 font-semibold text-muted-foreground">
            Safety invariants
          </div>
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="font-mono text-muted-foreground">
                businessMutationEnabled
              </span>
              <StatusPill
                tone={
                  readiness.businessMutationEnabled
                    ? "danger"
                    : "success"
                }
              >
                {String(readiness.businessMutationEnabled)}
              </StatusPill>
            </div>
            <div className="flex items-center justify-between">
              <span className="font-mono text-muted-foreground">
                customerNotificationEnabled
              </span>
              <StatusPill
                tone={
                  readiness.customerNotificationEnabled
                    ? "danger"
                    : "success"
                }
              >
                {String(readiness.customerNotificationEnabled)}
              </StatusPill>
            </div>
            <div className="flex items-center justify-between">
              <span className="font-mono text-muted-foreground">
                storeRawPayload
              </span>
              <StatusPill
                tone={readiness.storeRawPayload ? "warning" : "success"}
              >
                {String(readiness.storeRawPayload)}
              </StatusPill>
            </div>
          </div>
        </div>
        <div className="rounded-md border border-border bg-muted/20 p-3 text-xs">
          <div className="mb-2 font-semibold text-muted-foreground">
            Counters (must stay 0)
          </div>
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="font-mono text-muted-foreground">
                businessMutationCount
              </span>
              <StatusPill
                tone={
                  readiness.businessMutationCount === 0
                    ? "success"
                    : "danger"
                }
              >
                {readiness.businessMutationCount}
              </StatusPill>
            </div>
            <div className="flex items-center justify-between">
              <span className="font-mono text-muted-foreground">
                customerNotificationCount
              </span>
              <StatusPill
                tone={
                  readiness.customerNotificationCount === 0
                    ? "success"
                    : "danger"
                }
              >
                {readiness.customerNotificationCount}
              </StatusPill>
            </div>
            <div className="flex items-center justify-between">
              <span className="font-mono text-muted-foreground">
                rawSecretExposureCount
              </span>
              <StatusPill
                tone={
                  readiness.rawSecretExposureCount === 0
                    ? "success"
                    : "danger"
                }
              >
                {readiness.rawSecretExposureCount}
              </StatusPill>
            </div>
            <div className="flex items-center justify-between">
              <span className="font-mono text-muted-foreground">
                fullPiiExposureCount
              </span>
              <StatusPill
                tone={
                  readiness.fullPiiExposureCount === 0
                    ? "success"
                    : "danger"
                }
              >
                {readiness.fullPiiExposureCount}
              </StatusPill>
            </div>
          </div>
        </div>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-4 text-xs">
        <KeyValue label="Events seen" value={String(readiness.eventCount)} />
        <KeyValue
          label="Verified"
          value={String(readiness.verifiedEventCount)}
        />
        <KeyValue
          label="Duplicates"
          value={String(readiness.duplicateEventCount)}
        />
        <KeyValue
          label="Blocked / ignored"
          value={String(readiness.blockedEventCount)}
        />
      </div>
      {readiness.blockers.length > 0 && (
        <IssueList items={readiness.blockers} empty="No blockers" />
      )}
      <div className="mt-3 text-[11px] text-muted-foreground">
        Next action:{" "}
        <span className="font-medium">{readiness.nextAction}</span>
      </div>
    </div>
  );
}

function RazorpayWebhookEventsTable({
  response,
}: {
  response: SaasRazorpayWebhookEventsResponse;
}) {
  if (!response.events.length) {
    return (
      <div className="border-t border-border px-6 py-3 text-xs text-muted-foreground">
        No Razorpay webhook events recorded yet. Send a synthetic
        event via{" "}
        <code>manage.py simulate_razorpay_webhook_event --event payment.captured</code>.
      </div>
    );
  }
  return (
    <div className="overflow-x-auto border-t border-border">
      <table className="w-full min-w-[920px] text-sm">
        <thead className="bg-muted/30 text-[11px] uppercase text-muted-foreground">
          <tr>
            <th className="px-6 py-3 text-left font-medium">Event id</th>
            <th className="py-3 text-left font-medium">Event</th>
            <th className="py-3 text-left font-medium">Signature</th>
            <th className="py-3 text-left font-medium">Idempotency</th>
            <th className="py-3 text-left font-medium">Status</th>
            <th className="py-3 text-left font-medium">Order id</th>
            <th className="py-3 text-left font-medium">Payment id</th>
            <th className="py-3 text-left font-medium">Amount</th>
            <th className="px-6 py-3 text-left font-medium">Received</th>
          </tr>
        </thead>
        <tbody>
          {response.events.map((row) => (
            <RazorpayWebhookEventRow key={row.id} row={row} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RazorpayWebhookEventRow({
  row,
}: {
  row: SaasRazorpayWebhookEventDto;
}) {
  return (
    <tr
      className="border-t border-border/60"
      data-testid="razorpay-webhook-event-row"
    >
      <td className="px-6 py-3 font-mono text-xs">
        {row.sourceEventId || "—"}
      </td>
      <td className="py-3 text-xs">{row.eventName}</td>
      <td className="py-3">
        <StatusPill tone={row.signatureValid ? "success" : "danger"}>
          {row.signatureValid ? "valid" : "invalid"}
        </StatusPill>
      </td>
      <td className="py-3 text-xs">
        {row.idempotencyStatus} ({row.duplicateCount}x)
      </td>
      <td className="py-3">
        <StatusPill tone={toneForStatus(row.processingStatus)}>
          {row.processingStatus}
        </StatusPill>
      </td>
      <td className="py-3 text-[11px] font-mono">
        {row.providerOrderId || "—"}
      </td>
      <td className="py-3 text-[11px] font-mono">
        {row.providerPaymentId || "—"}
      </td>
      <td className="py-3 text-xs">
        {row.amountPaise === null
          ? "—"
          : `${row.amountPaise} ${row.currency || ""}`}
      </td>
      <td className="px-6 py-3 text-[11px] text-muted-foreground">
        {row.receivedAt}
      </td>
    </tr>
  );
}
