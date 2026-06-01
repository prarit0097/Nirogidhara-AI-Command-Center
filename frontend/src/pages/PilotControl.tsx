import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, isApiError } from "@/services/api";
import type {
  PilotControlSummary,
  PilotGateResult,
  PilotPlan,
  PilotPlanAction,
  PilotPlanType,
} from "@/types/domain";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  Lock,
  PlayCircle,
  Rocket,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

const STATUS_STYLES: Record<string, string> = {
  draft: "bg-muted text-muted-foreground",
  ready_for_review: "bg-warning/20 text-warning",
  approved_internal: "bg-primary/15 text-primary",
  running_internal: "bg-success/15 text-success",
  paused: "bg-warning/20 text-warning",
  completed: "bg-success/15 text-success",
  cancelled: "bg-destructive/15 text-destructive",
};

const GATE_STYLES: Record<string, string> = {
  pass: "bg-success/15 text-success",
  blocked: "bg-destructive/15 text-destructive",
  warning: "bg-warning/20 text-warning",
  skipped: "bg-muted text-muted-foreground",
};

const PILOT_TYPES: { value: PilotPlanType; label: string }[] = [
  { value: "full_lifecycle", label: "Full lifecycle" },
  { value: "imported_campaign", label: "Imported campaign" },
  { value: "fresh_leads", label: "Fresh leads" },
  { value: "existing_orders", label: "Existing orders" },
  { value: "payment_logistics", label: "Payment / logistics" },
];

// Internal-only actions — these change ONLY the internal pilot record state.
const ACTIONS: { action: PilotPlanAction; label: string }[] = [
  { action: "mark_ready", label: "Mark ready for review" },
  { action: "approve_internal", label: "Approve internal pilot" },
  { action: "start_internal", label: "Start internal pilot" },
  { action: "pause", label: "Pause pilot" },
  { action: "resume_internal", label: "Resume internal pilot" },
  { action: "complete", label: "Complete pilot" },
  { action: "cancel", label: "Cancel pilot" },
];

export default function PilotControl() {
  const [summary, setSummary] = useState<PilotControlSummary | null>(null);
  const [plans, setPlans] = useState<PilotPlan[]>([]);
  const [selected, setSelected] = useState<PilotPlan | null>(null);
  const [loading, setLoading] = useState(true);
  const [errored, setErrored] = useState(false);
  const [busy, setBusy] = useState(false);

  const [name, setName] = useState("");
  const [pilotType, setPilotType] = useState<PilotPlanType>("full_lifecycle");
  const [ownerTeam, setOwnerTeam] = useState("");
  const [objective, setObjective] = useState("");

  const load = () => {
    setLoading(true);
    Promise.all([
      api.getPilotControlSummary().then(setSummary),
      api
        .getPilotPlans()
        .then((r) => setPlans(r.items))
        .catch(() => setPlans([])),
    ])
      .catch(() => {
        setSummary(null);
        setErrored(true);
      })
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const openPlan = async (id: number) => {
    try {
      const detail = await api.getPilotPlan(id);
      setSelected(detail);
    } catch {
      toast.error("Could not open pilot plan.");
    }
  };

  const handleCreate = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const created = await api.createPilotPlan({
        name: name.trim() || `Internal pilot ${new Date().toISOString().slice(0, 16)}`,
        pilotType,
        ownerTeam: ownerTeam.trim(),
        objective: objective.trim(),
        safetyAcknowledged: true,
      });
      toast.success(`Internal pilot plan created: ${created.status}.`);
      setName("");
      setObjective("");
      setOwnerTeam("");
      load();
      openPlan(created.id);
    } catch (err) {
      if (isApiError(err)) toast.error(`Create failed (HTTP ${err.httpStatus}).`);
      else toast.error("Create failed. Please retry.");
    } finally {
      setBusy(false);
    }
  };

  const handleTransition = async (action: PilotPlanAction) => {
    if (!selected || busy) return;
    setBusy(true);
    try {
      const updated = await api.transitionPilotPlan(selected.id, { action });
      toast.success(`Pilot status: ${updated.status}.`);
      setSelected(updated);
      load();
    } catch (err) {
      if (isApiError(err)) {
        toast.error(
          err.httpStatus === 409
            ? "Transition not allowed from the current status."
            : `Transition failed (HTTP ${err.httpStatus}).`,
        );
      } else {
        toast.error("Transition failed. Please retry.");
      }
    } finally {
      setBusy(false);
    }
  };

  const handleReview = async () => {
    if (!selected || busy) return;
    setBusy(true);
    try {
      await api.reviewPilotPlan(selected.id, {
        decision: "reviewed",
        note: "Director internal note.",
      });
      toast.success("Director note recorded (internal only).");
      openPlan(selected.id);
    } catch {
      toast.error("Could not record note.");
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="h-96 grid place-items-center text-muted-foreground">
        Loading pilot control center...
      </div>
    );
  }

  if (errored || !summary) {
    return (
      <div data-testid="pilot-control-page">
        <PageHeader eyebrow="Operations" title="Internal Pilot Control Center" />
        <div
          data-testid="pilot-control-error"
          className="surface-elevated p-6 text-destructive text-[14px]"
        >
          Could not load the pilot control center. Please retry.
        </div>
      </div>
    );
  }

  const safety = summary.safety;

  return (
    <div data-testid="pilot-control-page">
      <PageHeader
        eyebrow="Operations"
        title="Internal Pilot Control Center"
        description="Create, configure, approve, monitor, pause and review a controlled pilot — internal control only, no live provider automation."
      />

      {/* Safety banner */}
      <div
        data-testid="pilot-control-safety-copy"
        className="mb-6 flex items-start gap-2 rounded-xl border border-border bg-muted/40 px-4 py-3 text-[13px] text-muted-foreground"
      >
        <ShieldCheck className="h-4 w-4 mt-0.5 shrink-0 text-success" />
        <span>
          Internal control only — no live provider automation. Starting or running
          an internal pilot here NEVER sends WhatsApp, takes a payment, books a
          shipment, places a call, or invokes any AI provider. Live provider
          actions stay locked behind a future Director live gate.
        </span>
      </div>

      {/* Safety chips */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <Chip label="AI" value={safety.aiPaused ? "Paused" : "Running"} tone={safety.aiPaused ? "success" : "warning"} />
        <Chip label="Sandbox" value={safety.sandboxOn ? "ON" : "OFF"} tone="success" />
        <Chip label="Sync" value={safety.syncLive ? "Live" : "Offline"} tone="success" />
        <Chip label="Live provider actions" value={safety.providerLiveActionsLocked ? "Locked" : "Open"} tone={safety.providerLiveActionsLocked ? "success" : "danger"} />
      </div>

      {/* Status counts */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3 mb-6" data-testid="pilot-control-summary">
        {Object.entries(summary.statusCounts).map(([status, count]) => (
          <div key={status} className="rounded-lg border border-border bg-muted/30 px-3 py-2">
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
              {status.replace(/_/g, " ")}
            </div>
            <div className="text-[18px] font-semibold">{count}</div>
          </div>
        ))}
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        {/* Create pilot plan */}
        <div className="surface-elevated p-6" data-testid="pilot-create-form">
          <h3 className="font-display text-lg font-semibold flex items-center gap-2 mb-3">
            <Rocket className="h-5 w-5 text-accent" /> Create pilot plan
          </h3>
          <div className="space-y-3">
            <div>
              <label className="text-[11px] uppercase tracking-wider text-muted-foreground">Pilot name</label>
              <Input
                data-testid="pilot-create-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={busy}
                placeholder="e.g. Joint pain internal pilot"
              />
            </div>
            <div>
              <label className="text-[11px] uppercase tracking-wider text-muted-foreground block">Pilot type</label>
              <select
                data-testid="pilot-create-type"
                aria-label="Pilot type"
                value={pilotType}
                onChange={(e) => setPilotType(e.target.value as PilotPlanType)}
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-[13.5px]"
              >
                {PILOT_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[11px] uppercase tracking-wider text-muted-foreground">Pilot owner / team</label>
              <Input
                data-testid="pilot-create-owner"
                value={ownerTeam}
                onChange={(e) => setOwnerTeam(e.target.value)}
                disabled={busy}
                placeholder="e.g. director_admin"
              />
            </div>
            <div>
              <label className="text-[11px] uppercase tracking-wider text-muted-foreground">Internal objective</label>
              <Input
                data-testid="pilot-create-objective"
                value={objective}
                onChange={(e) => setObjective(e.target.value)}
                disabled={busy}
                placeholder="e.g. Rehearse the full internal lifecycle"
              />
            </div>
            <Button data-testid="pilot-create-button" onClick={handleCreate} disabled={busy} className="w-full">
              {busy ? "Working…" : "Create internal pilot plan"}
            </Button>
            <p className="text-[11px] text-muted-foreground">
              Creating a plan never triggers a provider. It is an internal control
              record only and always records live provider actions as blocked.
            </p>
          </div>
        </div>

        {/* Pilot plan list */}
        <div className="surface-elevated p-6">
          <h3 className="font-display text-lg font-semibold mb-3">Pilot plans ({plans.length})</h3>
          {plans.length === 0 ? (
            <p data-testid="pilot-plans-empty" className="text-muted-foreground text-[14px]">
              No pilot plans yet. Create one on the left.
            </p>
          ) : (
            <div className="space-y-2" data-testid="pilot-plans-list">
              {plans.map((p) => (
                <button
                  key={p.id}
                  data-testid={`pilot-plan-${p.id}`}
                  onClick={() => openPlan(p.id)}
                  className="w-full text-left rounded-lg border border-border bg-muted/20 px-3 py-2 hover:bg-muted/40 transition-colors"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium truncate">{p.name}</span>
                    <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase ${STATUS_STYLES[p.status] ?? STATUS_STYLES.draft}`}>
                      {p.status.replace(/_/g, " ")}
                    </span>
                  </div>
                  <div className="text-[12px] text-muted-foreground mt-0.5">
                    {p.pilotType.replace(/_/g, " ")} · {p.ownerTeam || "no owner"}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Selected plan detail */}
      {selected && (
        <div className="surface-elevated p-6 mt-6" data-testid="pilot-plan-detail">
          <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
            <h3 className="font-display text-lg font-semibold flex items-center gap-2">
              <ClipboardCheck className="h-5 w-5 text-accent" /> {selected.name}
            </h3>
            <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase ${STATUS_STYLES[selected.status] ?? STATUS_STYLES.draft}`}>
              {selected.status.replace(/_/g, " ")}
            </span>
          </div>

          {/* Internal-only actions */}
          <div className="flex flex-wrap gap-2 mb-5" data-testid="pilot-plan-actions">
            {ACTIONS.map((a) => (
              <Button
                key={a.action}
                data-testid={`pilot-action-${a.action}`}
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => handleTransition(a.action)}
              >
                {a.label}
              </Button>
            ))}
            <Button
              data-testid="pilot-action-note"
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={handleReview}
            >
              Add Director note
            </Button>
          </div>

          {/* Gate checklist */}
          <h4 className="font-medium flex items-center gap-2 mb-2">
            <CheckCircle2 className="h-4 w-4 text-primary" /> Pilot gate checklist
          </h4>
          <div className="overflow-x-auto mb-5">
            <table data-testid="pilot-gate-checklist" className="w-full text-[13px] border-collapse">
              <tbody>
                {(selected.gateStatus ?? []).map((g) => (
                  <GateRow key={g.key} gate={g} />
                ))}
              </tbody>
            </table>
          </div>

          {/* Blocked live actions */}
          <h4 className="font-medium flex items-center gap-2 mb-2">
            <Lock className="h-4 w-4 text-destructive" /> Blocked live actions
          </h4>
          <ul className="space-y-1 text-[12.5px] text-muted-foreground list-disc pl-5 mb-5">
            {(selected.metrics?.blockedLiveActions ?? []).map((r, idx) => (
              <li key={idx}>{r}</li>
            ))}
          </ul>

          {/* Recent events */}
          <h4 className="font-medium flex items-center gap-2 mb-2">
            <PlayCircle className="h-4 w-4 text-accent" /> Recent pilot events
          </h4>
          {(selected.events ?? []).length === 0 ? (
            <p className="text-muted-foreground text-[13px]">No events yet.</p>
          ) : (
            <ul data-testid="pilot-plan-events" className="space-y-1.5 text-[13px]">
              {(selected.events ?? []).map((e) => (
                <li key={e.id} className="flex items-center justify-between gap-2 border-b border-border/50 pb-1.5 last:border-0">
                  <span className="font-medium">{e.eventType.replace(/_/g, " ")}</span>
                  <span className="text-muted-foreground text-[12px]">{e.actor ?? "—"}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function Chip({ label, value, tone }: { label: string; value: string; tone?: "success" | "warning" | "danger" }) {
  const toneClass =
    tone === "success" ? "text-success" : tone === "warning" ? "text-warning" : tone === "danger" ? "text-destructive" : "text-foreground";
  return (
    <div className="rounded-lg border border-border bg-muted/30 px-3 py-2">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={`text-[15px] font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}

function GateRow({ gate }: { gate: PilotGateResult }) {
  return (
    <tr className="border-b border-border/60 last:border-0 align-top">
      <td className="py-1.5 pr-3 font-medium">{gate.label}</td>
      <td className="py-1.5 pr-3">
        <span
          data-testid={`pilot-gate-${gate.key}`}
          className={`rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase ${GATE_STYLES[gate.status] ?? GATE_STYLES.skipped}`}
        >
          {gate.status === "warning" && <AlertTriangle className="inline h-3 w-3 mr-1" />}
          {gate.status}
        </span>
      </td>
      <td className="py-1.5 pr-3 text-muted-foreground text-[12px]">{gate.detail}</td>
    </tr>
  );
}
