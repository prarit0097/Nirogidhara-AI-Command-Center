import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  CircleSlash,
  Clock,
  Eye,
  Lock,
  Phone,
  RefreshCw,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Send,
  Users,
  XCircle,
} from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { api } from "@/services/api";
import type {
  WhatsAppMonitoringActivity,
  WhatsAppMonitoringAuditEvent,
  WhatsAppMonitoringAuditResponse,
  WhatsAppMonitoringCohort,
  WhatsAppMonitoringMutationSafety,
  WhatsAppMonitoringOverview,
  WhatsAppMonitoringPilot,
  WhatsAppMonitoringStatus,
  WhatsAppMonitoringUnexpectedOutbound,
} from "@/types/domain";

const REFRESH_INTERVAL_MS = 30_000;

function statusBadge(status: WhatsAppMonitoringStatus): {
  label: string;
  className: string;
  Icon: typeof Shield;
} {
  switch (status) {
    case "limited_auto_reply_on":
      return {
        label: "Limited Auto-Reply ON",
        className:
          "bg-success/15 text-success border border-success/40",
        Icon: ShieldCheck,
      };
    case "danger":
      return {
        label: "Danger / Roll back",
        className:
          "bg-destructive/15 text-destructive border border-destructive/40",
        Icon: ShieldAlert,
      };
    case "needs_attention":
      return {
        label: "Needs attention",
        className:
          "bg-warning/15 text-warning border border-warning/40",
        Icon: AlertTriangle,
      };
    case "safe_off":
    default:
      return {
        label: "Safe OFF",
        className:
          "bg-muted text-muted-foreground border border-border/60",
        Icon: Shield,
      };
  }
}

function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.valueOf())) return iso;
  const diffMin = Math.round((Date.now() - d.valueOf()) / 60_000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin} min ago`;
  if (diffMin < 1440) return `${Math.round(diffMin / 60)}h ago`;
  return d.toLocaleString();
}

function StatusCard({
  label,
  value,
  ok,
  warn,
  Icon,
}: {
  label: string;
  value: string;
  ok?: boolean;
  warn?: boolean;
  Icon: typeof Shield;
}) {
  const tone = warn
    ? "text-warning"
    : ok
    ? "text-success"
    : "text-muted-foreground";
  return (
    <div className="surface-card p-4">
      <div className="flex items-center gap-2 text-xs text-muted-foreground uppercase tracking-wide mb-1.5">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <div className={`text-lg font-semibold ${tone}`}>{value}</div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  hint,
  warn,
  Icon,
}: {
  label: string;
  value: number | string;
  hint?: string;
  warn?: boolean;
  Icon: typeof Activity;
}) {
  return (
    <div className="surface-card p-4">
      <div className="flex items-center gap-2 text-xs text-muted-foreground uppercase tracking-wide mb-1">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <div
        className={`text-2xl font-semibold ${
          warn ? "text-warning" : "text-foreground"
        }`}
      >
        {value}
      </div>
      {hint && (
        <div className="text-xs text-muted-foreground mt-1">{hint}</div>
      )}
    </div>
  );
}

function FlagPill({
  label,
  enabled,
}: {
  label: string;
  enabled: boolean;
}) {
  if (enabled) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-warning/40 bg-warning/10 px-2.5 py-1 text-xs font-medium text-warning">
        <AlertTriangle className="h-3 w-3" />
        {label}: ON
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
      <Lock className="h-3 w-3" />
      {label}: OFF / locked
    </span>
  );
}

function GateSection({ overview }: { overview: WhatsAppMonitoringOverview }) {
  const gate = overview.gate;
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold text-foreground uppercase tracking-wide">
        Gate status
      </h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <StatusCard
          label="Provider"
          value={gate.provider}
          ok={gate.provider === "meta_cloud"}
          warn={gate.provider !== "meta_cloud"}
          Icon={Phone}
        />
        <StatusCard
          label="Limited test mode"
          value={gate.limitedTestMode ? "ON" : "OFF"}
          ok={gate.limitedTestMode}
          warn={!gate.limitedTestMode}
          Icon={Shield}
        />
        <StatusCard
          label="Auto-reply enabled"
          value={gate.autoReplyEnabled ? "ON" : "OFF"}
          ok={!gate.autoReplyEnabled}
          warn={gate.autoReplyEnabled && !gate.readyForLimitedAutoReply}
          Icon={Send}
        />
        <StatusCard
          label="Allowed list size"
          value={String(gate.allowedListSize)}
          ok={gate.allowedListSize > 0}
          warn={gate.allowedListSize === 0}
          Icon={Users}
        />
        <StatusCard
          label="WABA active"
          value={
            gate.wabaSubscription.checked
              ? gate.wabaSubscription.active
                ? `Yes (${gate.wabaSubscription.subscribedAppCount})`
                : "No"
              : "Unchecked"
          }
          ok={gate.wabaSubscription.active === true}
          warn={gate.wabaSubscription.active === false}
          Icon={CheckCircle2}
        />
        <StatusCard
          label="Campaigns locked"
          value={gate.campaignsLocked ? "Locked" : "Unlocked"}
          ok={gate.campaignsLocked}
          warn={!gate.campaignsLocked}
          Icon={Lock}
        />
        <StatusCard
          label="Final-send guard"
          value={gate.finalSendGuardActive ? "Active" : "Inactive"}
          ok={gate.finalSendGuardActive}
          Icon={ShieldCheck}
        />
        <StatusCard
          label="Consent + Claim Vault"
          value="Required"
          ok={gate.consentRequired && gate.claimVaultRequired}
          Icon={ShieldCheck}
        />
      </div>
      {gate.allowedNumbersMasked.length > 0 && (
        <div className="text-xs text-muted-foreground">
          Allowed numbers: {gate.allowedNumbersMasked.join(", ")}
        </div>
      )}
    </section>
  );
}

function SafetyFlagsSection({ gate }: { gate: WhatsAppMonitoringOverview["gate"] }) {
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold text-foreground uppercase tracking-wide">
        Broad automation flags (must remain OFF)
      </h2>
      <div className="flex flex-wrap gap-2">
        <FlagPill label="Call handoff" enabled={gate.callHandoffEnabled} />
        <FlagPill label="Lifecycle" enabled={gate.lifecycleEnabled} />
        <FlagPill
          label="Rescue discount"
          enabled={gate.rescueDiscountEnabled}
        />
        <FlagPill label="RTO rescue" enabled={gate.rtoRescueEnabled} />
        <FlagPill label="Reorder Day-20" enabled={gate.reorderEnabled} />
        <FlagPill label="Campaigns" enabled={!gate.campaignsLocked} />
      </div>
    </section>
  );
}

function PilotSection({ pilot }: { pilot: WhatsAppMonitoringPilot }) {
  return (
    <section className="space-y-3">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-foreground uppercase tracking-wide">
            Approved Customer Pilot Readiness
          </h2>
          <div className="text-xs text-muted-foreground mt-1">
            Read-only prep view. Auto-reply remains OFF; campaigns and
            broadcast stay locked.
          </div>
        </div>
        <div className="font-mono text-xs text-muted-foreground">
          {pilot.nextAction}
        </div>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <MetricCard label="Pilot members" value={pilot.totalPilotMembers} Icon={Users} />
        <MetricCard label="Approved" value={pilot.approvedCount} Icon={CheckCircle2} />
        <MetricCard label="Pending" value={pilot.pendingCount} warn={pilot.pendingCount > 0} Icon={Clock} />
        <MetricCard label="Paused" value={pilot.pausedCount} warn={pilot.pausedCount > 0} Icon={CircleSlash} />
        <MetricCard label="Consent missing" value={pilot.consentMissingCount} warn={pilot.consentMissingCount > 0} Icon={ShieldAlert} />
        <MetricCard label="Ready" value={pilot.readyForPilotCount} Icon={ShieldCheck} />
      </div>
      {pilot.blockers.length > 0 && (
        <div className="surface-card p-4 border-warning/40">
          <div className="text-sm font-semibold text-warning mb-2 flex items-center gap-1.5">
            <AlertTriangle className="h-4 w-4" />
            Pilot blockers
          </div>
          <ul className="space-y-1 text-xs text-muted-foreground">
            {pilot.blockers.map((blocker) => (
              <li key={blocker}>{blocker}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="surface-card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted/50">
            <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
              <th className="px-4 py-2 font-medium">Phone (masked)</th>
              <th className="px-4 py-2 font-medium">Customer</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium">Consent</th>
              <th className="px-4 py-2 font-medium">Daily cap</th>
              <th className="px-4 py-2 font-medium">Last inbound</th>
              <th className="px-4 py-2 font-medium">Latest status</th>
              <th className="px-4 py-2 font-medium">Ready</th>
            </tr>
          </thead>
          <tbody>
            {pilot.members.map((member) => (
              <tr key={member.customerId} className="border-t border-border/60">
                <td className="px-4 py-2 font-mono">{member.maskedPhone}</td>
                <td className="px-4 py-2 text-xs">{member.customerName}</td>
                <td className="px-4 py-2 text-xs">{member.status}</td>
                <td className="px-4 py-2 text-xs">
                  {member.consentVerified ? "Verified" : "Missing"}
                </td>
                <td className="px-4 py-2 text-xs">{member.dailyCap}/day</td>
                <td className="px-4 py-2 text-xs text-muted-foreground">
                  {fmtRelative(member.lastInboundAt)}
                </td>
                <td className="px-4 py-2 text-xs">
                  {member.latestStatus || "none"}
                </td>
                <td className="px-4 py-2">
                  {member.ready ? (
                    <span className="inline-flex items-center gap-1 text-xs text-success">
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      Ready
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-xs text-warning">
                      <CircleSlash className="h-3.5 w-3.5" />
                      Blocked
                    </span>
                  )}
                </td>
              </tr>
            ))}
            {pilot.members.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-6 text-center text-sm text-muted-foreground">
                  No approved customer pilot members prepared yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ActivitySection({
  activity,
}: {
  activity: WhatsAppMonitoringActivity;
}) {
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold text-foreground uppercase tracking-wide">
        Activity (last {activity.windowHours.toFixed(2)}h)
      </h2>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        <MetricCard
          label="Inbound"
          value={activity.inboundMessageCount}
          Icon={Activity}
        />
        <MetricCard
          label="Outbound"
          value={activity.outboundMessageCount}
          Icon={Send}
        />
        <MetricCard
          label="Auto replies sent"
          value={activity.replyAutoSentCount}
          Icon={Send}
        />
        <MetricCard
          label="Deterministic builder"
          value={activity.deterministicBuilderUsedCount}
          Icon={ShieldCheck}
        />
        <MetricCard
          label="Objection replies"
          value={activity.objectionReplyUsedCount}
          Icon={ShieldCheck}
        />
        <MetricCard
          label="Blocked replies"
          value={activity.replyBlockedCount}
          Icon={CircleSlash}
        />
        <MetricCard
          label="Delivered"
          value={activity.messageDeliveredCount}
          Icon={CheckCircle2}
        />
        <MetricCard
          label="Read"
          value={activity.messageReadCount}
          Icon={Eye}
        />
        <MetricCard
          label="Guard blocks"
          value={activity.autoReplyGuardBlockedCount}
          warn={activity.autoReplyGuardBlockedCount > 0}
          Icon={Shield}
        />
        <MetricCard
          label="Unexpected non-allowed sends"
          value={activity.unexpectedNonAllowedSendsCount}
          warn={activity.unexpectedNonAllowedSendsCount > 0}
          Icon={ShieldAlert}
        />
      </div>
    </section>
  );
}

function MutationSafetySection({
  mutation,
  unexpected,
}: {
  mutation: WhatsAppMonitoringMutationSafety;
  unexpected: WhatsAppMonitoringUnexpectedOutbound;
}) {
  const clean = mutation.allClean && unexpected.unexpectedSendsCount === 0;
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-foreground uppercase tracking-wide">
          Mutation safety (last {mutation.windowHours.toFixed(2)}h)
        </h2>
        <span
          className={`inline-flex items-center gap-1.5 text-xs font-medium ${
            clean ? "text-success" : "text-destructive"
          }`}
        >
          {clean ? (
            <>
              <CheckCircle2 className="h-4 w-4" />
              All clean — auto-reply path mutated nothing
            </>
          ) : (
            <>
              <ShieldAlert className="h-4 w-4" />
              Investigate — non-zero mutation in window
            </>
          )}
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <MetricCard
          label="Orders"
          value={mutation.ordersCreatedInWindow}
          warn={mutation.ordersCreatedInWindow > 0}
          Icon={Activity}
        />
        <MetricCard
          label="Payments"
          value={mutation.paymentsCreatedInWindow}
          warn={mutation.paymentsCreatedInWindow > 0}
          Icon={Activity}
        />
        <MetricCard
          label="Shipments"
          value={mutation.shipmentsCreatedInWindow}
          warn={mutation.shipmentsCreatedInWindow > 0}
          Icon={Activity}
        />
        <MetricCard
          label="Discount logs"
          value={mutation.discountOfferLogsCreatedInWindow}
          warn={mutation.discountOfferLogsCreatedInWindow > 0}
          Icon={Activity}
        />
        <MetricCard
          label="Lifecycle events"
          value={mutation.lifecycleEventsInWindow}
          warn={mutation.lifecycleEventsInWindow > 0}
          Icon={Activity}
        />
        <MetricCard
          label="Handoff events"
          value={mutation.handoffEventsInWindow}
          warn={mutation.handoffEventsInWindow > 0}
          Icon={Activity}
        />
      </div>
      {unexpected.unexpectedSendsCount > 0 && (
        <div className="surface-card p-4 border-destructive/40">
          <div className="text-sm font-semibold text-destructive mb-2 flex items-center gap-1.5">
            <ShieldAlert className="h-4 w-4" />
            {unexpected.unexpectedSendsCount} unexpected send(s) outside
            allow-list — rollback recommended
          </div>
          <ul className="space-y-1 text-xs text-muted-foreground">
            {unexpected.breakdown.map((row) => (
              <li key={row.messageId}>
                {row.messageId} → ****{row.phoneSuffix} ·{" "}
                {row.status} · {fmtRelative(row.sentAt)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function CohortSection({ cohort }: { cohort: WhatsAppMonitoringCohort }) {
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold text-foreground uppercase tracking-wide">
        Internal cohort ({cohort.allowedListSize})
      </h2>
      <div className="surface-card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted/50">
            <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
              <th className="px-4 py-2 font-medium">Phone (masked)</th>
              <th className="px-4 py-2 font-medium">Suffix</th>
              <th className="px-4 py-2 font-medium">Customer</th>
              <th className="px-4 py-2 font-medium">Consent</th>
              <th className="px-4 py-2 font-medium">Latest inbound</th>
              <th className="px-4 py-2 font-medium">Latest outbound</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium">Ready</th>
            </tr>
          </thead>
          <tbody>
            {cohort.cohort.map((entry) => (
              <tr
                key={entry.suffix || entry.maskedPhone}
                className="border-t border-border/60"
              >
                <td className="px-4 py-2 font-mono">{entry.maskedPhone}</td>
                <td className="px-4 py-2 font-mono text-xs text-muted-foreground">
                  {entry.suffix}
                </td>
                <td className="px-4 py-2 text-xs">
                  {entry.customerFound ? "Found" : "Missing"}
                </td>
                <td className="px-4 py-2 text-xs">
                  {entry.consentState || "—"}
                </td>
                <td className="px-4 py-2 text-xs text-muted-foreground">
                  {fmtRelative(entry.latestInboundAt)}
                </td>
                <td className="px-4 py-2 text-xs text-muted-foreground">
                  {fmtRelative(entry.latestOutboundAt)}
                </td>
                <td className="px-4 py-2 text-xs">
                  {entry.latestOutboundStatus || "—"}
                </td>
                <td className="px-4 py-2">
                  {entry.readyForControlledTest ? (
                    <span className="inline-flex items-center gap-1 text-xs text-success">
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      Ready
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-xs text-warning">
                      <CircleSlash className="h-3.5 w-3.5" />
                      Setup
                    </span>
                  )}
                </td>
              </tr>
            ))}
            {cohort.cohort.length === 0 && (
              <tr>
                <td
                  colSpan={8}
                  className="px-4 py-6 text-center text-sm text-muted-foreground"
                >
                  Allow-list is empty.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function AuditTimelineSection({
  events,
}: {
  events: WhatsAppMonitoringAuditEvent[];
}) {
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold text-foreground uppercase tracking-wide">
        Recent audit events
      </h2>
      <div className="surface-card divide-y divide-border/60">
        {events.length === 0 && (
          <div className="px-4 py-6 text-sm text-muted-foreground text-center">
            No WhatsApp audit events in the window.
          </div>
        )}
        {events.map((event) => {
          const tone =
            event.tone === "danger"
              ? "text-destructive"
              : event.tone === "warning"
              ? "text-warning"
              : event.tone === "success"
              ? "text-success"
              : "text-muted-foreground";
          return (
            <div key={event.id} className="px-4 py-3 flex items-start gap-3">
              <div className={`mt-1 ${tone}`}>
                {event.tone === "danger" || event.tone === "warning" ? (
                  <AlertTriangle className="h-4 w-4" />
                ) : event.tone === "success" ? (
                  <CheckCircle2 className="h-4 w-4" />
                ) : (
                  <Activity className="h-4 w-4" />
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <span className="font-mono text-xs text-muted-foreground">
                    {event.kind}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {fmtRelative(event.occurredAt)}
                  </span>
                </div>
                <div className="text-sm text-foreground mt-0.5 break-words">
                  {event.text}
                </div>
                <div className="text-xs text-muted-foreground mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
                  {event.phoneSuffix && (
                    <span>****{event.phoneSuffix}</span>
                  )}
                  {event.category && <span>cat: {event.category}</span>}
                  {event.blockReason && (
                    <span>block: {event.blockReason}</span>
                  )}
                  {event.finalReplySource && (
                    <span>src: {event.finalReplySource}</span>
                  )}
                  {event.deterministicFallbackUsed && (
                    <span className="text-success">
                      fallback used
                    </span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function NextActionPanel({
  overview,
}: {
  overview: WhatsAppMonitoringOverview;
}) {
  return (
    <section className="surface-card p-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
      <div>
        <div className="text-xs uppercase tracking-wide text-muted-foreground">
          Backend recommendation (read-only)
        </div>
        <div className="font-mono text-sm text-foreground mt-1">
          {overview.nextAction || "—"}
        </div>
      </div>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Lock className="h-3.5 w-3.5" />
        Dashboard is read-only — flag flips happen on the VPS only.
      </div>
    </section>
  );
}

export default function WhatsAppMonitoringPage() {
  const [overview, setOverview] = useState<WhatsAppMonitoringOverview | null>(
    null,
  );
  const [auditResponse, setAuditResponse] =
    useState<WhatsAppMonitoringAuditResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<string>("");

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const [ov, audit] = await Promise.all([
        api.getWhatsAppMonitoringOverview(2),
        api.getWhatsAppMonitoringAudit(2, 25),
      ]);
      setOverview(ov);
      setAuditResponse(audit);
      setLastRefreshed(new Date().toISOString());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, REFRESH_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, []);

  const status = overview?.status ?? "safe_off";
  const badge = useMemo(() => statusBadge(status), [status]);
  const BadgeIcon = badge.Icon;

  return (
    <div className="space-y-6">
      <PageHeader
        title="WhatsApp Auto-Reply Monitoring"
        description="Read-only safety + activity dashboard for the limited auto-reply gate. No automation enable controls live here."
      />

      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div className="flex items-center gap-3">
          <span
            className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-semibold ${badge.className}`}
          >
            <BadgeIcon className="h-4 w-4" />
            {badge.label}
          </span>
          {overview?.rollbackReady && (
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
              <ShieldCheck className="h-3.5 w-3.5" />
              rollback ready
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground inline-flex items-center gap-1">
            <Clock className="h-3.5 w-3.5" />
            {lastRefreshed
              ? `Last refreshed ${fmtRelative(lastRefreshed)}`
              : "Refreshing…"}
          </span>
          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-md border border-border/60 bg-background px-3 py-1.5 text-sm font-medium text-foreground hover:bg-muted/50 disabled:opacity-50"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`}
            />
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="surface-card p-4 border-destructive/40 text-sm text-destructive">
          <XCircle className="h-4 w-4 inline mr-2" />
          {error}
        </div>
      )}

      {overview && (
        <>
          <NextActionPanel overview={overview} />
          <GateSection overview={overview} />
          <SafetyFlagsSection gate={overview.gate} />
          <PilotSection pilot={overview.pilot} />
          <ActivitySection activity={overview.activity} />
          <MutationSafetySection
            mutation={overview.mutationSafety}
            unexpected={overview.unexpectedOutbound}
          />
          <CohortSection cohort={overview.cohort} />
          <AuditTimelineSection events={auditResponse?.events ?? []} />
        </>
      )}
    </div>
  );
}
