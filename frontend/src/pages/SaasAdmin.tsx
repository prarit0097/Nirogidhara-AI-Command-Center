import { useEffect, useState, type ReactNode } from "react";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill, toneForStatus } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { api } from "@/services/api";
import type {
  SaasAdminOverview,
  SaasProviderReadiness,
} from "@/types/domain";
import {
  Building2,
  CheckCircle2,
  KeyRound,
  LockKeyhole,
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
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    api
      .getSaasAdminOverview()
      .then(setOverview)
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
