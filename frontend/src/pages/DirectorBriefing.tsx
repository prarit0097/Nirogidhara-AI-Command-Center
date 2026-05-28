import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api, isApiError } from "@/services/api";
import type {
  DirectorBriefingOverview,
  DirectorReviewDecisionStatus,
} from "@/types/domain";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  Lock,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

const DECISION_OPTIONS: { value: DirectorReviewDecisionStatus; label: string }[] = [
  { value: "reviewed", label: "Reviewed" },
  { value: "needs_action", label: "Needs action" },
  { value: "deferred", label: "Deferred" },
];

// Static decision checklist — these are the questions the Director answers in
// their own note; the page never auto-answers them or calls any provider.
const DECISION_CHECKLIST = [
  "Which team should pilot first?",
  "Which product / disease journey first?",
  "Should AI calling remain disabled?",
  "WhatsApp allowed-list size?",
  "Payment pilot mode?",
  "Delhivery pilot scope?",
  "Claim Vault production seed status?",
];

const PENDING_BLOCKERS = [
  "Director Daily Briefing UI (this page) — shipping in Phase 16C",
  "Team Roles UI — shipping in Phase 16C",
  "Shipment live hardening (ShipmentCreateView still mock) — deferred",
  "Payment / logistics / WhatsApp activation — not approved",
  "Claim Vault production seed (still demo) — pending",
];

const STATUS_STYLES: Record<string, string> = {
  fresh: "bg-success/15 text-success",
  stale: "bg-warning/20 text-warning",
  missing: "bg-muted text-muted-foreground",
  unavailable: "bg-muted text-muted-foreground",
};

export default function DirectorBriefing() {
  const [overview, setOverview] = useState<DirectorBriefingOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [note, setNote] = useState("");
  const [decision, setDecision] = useState<DirectorReviewDecisionStatus>("reviewed");
  const [saving, setSaving] = useState(false);

  const load = () => {
    setLoading(true);
    api
      .getDirectorBriefingOverview()
      .then(setOverview)
      .catch(() => setOverview(null))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleSave = async () => {
    if (decision === "needs_action" && !note.trim()) {
      toast.error("A note is required when marking 'Needs action'.");
      return;
    }
    setSaving(true);
    try {
      await api.createDirectorBriefingReview({
        note: note.trim(),
        decisionStatus: decision,
        snapshotRef: overview?.briefing.snapshotId ?? null,
      });
      toast.success("Director review recorded (internal only).");
      setNote("");
      setDecision("reviewed");
      load();
    } catch (err) {
      if (isApiError(err)) {
        toast.error(`Could not save review (HTTP ${err.httpStatus}).`);
      } else {
        toast.error("Could not save review. Please retry.");
      }
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="h-96 grid place-items-center text-muted-foreground">
        Loading Director briefing...
      </div>
    );
  }

  const briefing = overview?.briefing;
  const readiness = overview?.readiness;
  const isMissing = !briefing || briefing.status === "missing";

  return (
    <div data-testid="director-briefing-page">
      <PageHeader
        eyebrow="Leadership"
        title="Director Daily Briefing"
        description="Review the latest business briefing, decisions, and risks. Record an internal review note — no AI generation or live action is triggered here."
      />

      {/* Safety copy */}
      <div
        data-testid="briefing-safety-copy"
        className="mb-6 flex items-start gap-2 rounded-xl border border-border bg-muted/40 px-4 py-3 text-[13px] text-muted-foreground"
      >
        <ShieldCheck className="h-4 w-4 mt-0.5 shrink-0 text-success" />
        <span>
          Review-only: no WhatsApp / payment / courier / calling / AI provider
          action is triggered from this page. This page never generates a
          briefing.
        </span>
      </div>

      {/* Latest briefing status */}
      <div className="surface-elevated p-6 mb-6">
        <div className="flex items-center justify-between gap-4 mb-3">
          <h2 className="font-display text-xl font-semibold flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-accent" /> Latest briefing status
          </h2>
          {briefing && (
            <span
              data-testid="briefing-status-pill"
              data-briefing-status={briefing.status}
              className={`rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider ${
                STATUS_STYLES[briefing.status] ?? STATUS_STYLES.missing
              }`}
            >
              {briefing.status}
            </span>
          )}
        </div>

        {isMissing ? (
          <p
            data-testid="briefing-empty-state"
            className="text-muted-foreground text-[14px]"
          >
            No briefing snapshot available yet. This page does not generate a
            briefing or call AI providers.
          </p>
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 text-[13px]">
            <Metric label="Source" value={briefing.source} />
            <Metric
              label="Health score"
              value={
                briefing.healthScore != null ? `${briefing.healthScore}/100` : "—"
              }
            />
            <Metric label="Tier" value={briefing.healthTier ?? "—"} />
            <Metric
              label="Age"
              value={
                briefing.ageMinutes != null
                  ? `${briefing.ageMinutes} min`
                  : "—"
              }
            />
            {briefing.briefingText && (
              <div className="sm:col-span-2 lg:col-span-4">
                <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-1">
                  Briefing
                </div>
                <p className="text-[13.5px] leading-relaxed whitespace-pre-line">
                  {briefing.briefingText}
                </p>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="grid lg:grid-cols-2 gap-6 mb-6">
        {/* Business readiness */}
        <div className="surface-elevated p-6">
          <h3 className="font-display text-lg font-semibold flex items-center gap-2 mb-3">
            <CheckCircle2 className="h-5 w-5 text-success" /> Business readiness
          </h3>
          <ul className="space-y-2 text-[13.5px]">
            <ReadinessRow
              label="Current baseline"
              value={readiness?.baseline ?? "—"}
            />
            <ReadinessRow
              label="Safety shell"
              value={readiness?.safetyShellFrozen ? "Frozen" : "Unknown"}
            />
            <ReadinessRow
              label="Live automation"
              value={readiness?.liveAutomationApproved ? "Approved" : "Not approved"}
            />
            <ReadinessRow
              label="Current phase"
              value={readiness?.currentPhase ?? "—"}
            />
          </ul>
        </div>

        {/* Decision checklist */}
        <div className="surface-elevated p-6">
          <h3 className="font-display text-lg font-semibold flex items-center gap-2 mb-3">
            <ClipboardList className="h-5 w-5 text-accent" /> Decision checklist
          </h3>
          <ul className="space-y-2 text-[13.5px] text-muted-foreground list-disc pl-5">
            {DECISION_CHECKLIST.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ul>
        </div>
      </div>

      {/* Pending blockers / risks */}
      <div className="surface-elevated p-6 mb-6">
        <h3 className="font-display text-lg font-semibold flex items-center gap-2 mb-3">
          <AlertTriangle className="h-5 w-5 text-warning" /> Pending launch
          blockers / risks
        </h3>
        <ul className="space-y-2 text-[13.5px] text-muted-foreground list-disc pl-5">
          {PENDING_BLOCKERS.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      </div>

      {/* Safe action panel */}
      <div className="surface-elevated p-6" data-testid="briefing-review-form">
        <h3 className="font-display text-lg font-semibold flex items-center gap-2 mb-1">
          <Lock className="h-5 w-5 text-primary" /> Record Director decision
        </h3>
        <p className="text-[12.5px] text-muted-foreground mb-4">
          Internal-only. Saves a review/decision record inside the app. No
          provider, WhatsApp, payment, shipment, call, or AI generation runs.
        </p>

        {overview?.latestReview && (
          <div className="mb-4 rounded-lg border border-border bg-muted/30 px-3 py-2 text-[12.5px]">
            <span className="font-medium">Last review:</span>{" "}
            <span className="uppercase">{overview.latestReview.decisionStatus}</span>
            {overview.latestReview.note ? ` — ${overview.latestReview.note}` : ""}
          </div>
        )}

        <Textarea
          data-testid="briefing-note-input"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Director note / decision rationale (internal)"
          className="mb-3 min-h-[96px]"
        />
        <div className="flex flex-wrap items-center gap-3">
          <select
            data-testid="briefing-decision-select"
            aria-label="Decision status"
            value={decision}
            onChange={(e) =>
              setDecision(e.target.value as DirectorReviewDecisionStatus)
            }
            className="h-10 rounded-md border border-input bg-background px-3 text-[13.5px]"
          >
            {DECISION_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <Button
            data-testid="briefing-save-button"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? "Saving..." : "Record decision"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-muted/30 px-3 py-2">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="text-[14px] font-medium">{value}</div>
    </div>
  );
}

function ReadinessRow({ label, value }: { label: string; value: string }) {
  return (
    <li className="flex items-start justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium text-right">{value}</span>
    </li>
  );
}
