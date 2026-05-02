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
  SaasRuntimeDryRunOperationDecision,
  SaasRuntimeDryRunReport,
  SaasRuntimeRoutingProviderPreview,
  SaasRuntimeRoutingReadiness,
} from "@/types/domain";
import {
  Building2,
  CheckCircle2,
  Cpu,
  KeyRound,
  LockKeyhole,
  PlayCircle,
  RefreshCw,
  ShieldCheck,
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
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    Promise.all([
      api.getSaasAdminOverview(),
      api.getSaasRuntimeRoutingReadiness(),
      api.getSaasRuntimeDryRun(),
      api.getSaasAiProviderRouting(),
    ])
      .then(([ov, rt, dr, ai]) => {
        setOverview(ov);
        setRouting(rt);
        setDryRun(dr);
        setAiRouting(ai);
      })
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
