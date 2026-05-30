import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, isApiError } from "@/services/api";
import type {
  PilotDryRun,
  PilotGateResult,
  PilotReadiness as PilotReadinessType,
  PilotScenarioType,
} from "@/types/domain";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  Lock,
  PlayCircle,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

const GATE_STYLES: Record<string, string> = {
  pass: "bg-success/15 text-success",
  blocked: "bg-destructive/15 text-destructive",
  warning: "bg-warning/20 text-warning",
  skipped: "bg-muted text-muted-foreground",
};

const SCENARIOS: { value: PilotScenarioType; label: string }[] = [
  { value: "full_lifecycle", label: "Full lifecycle" },
  { value: "fresh_lead", label: "Fresh lead" },
  { value: "imported_campaign", label: "Imported campaign" },
  { value: "existing_order", label: "Existing order" },
  { value: "payment_logistics", label: "Payment / logistics" },
];

export default function PilotReadiness() {
  const [readiness, setReadiness] = useState<PilotReadinessType | null>(null);
  const [dryRuns, setDryRuns] = useState<PilotDryRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [errored, setErrored] = useState(false);
  const [name, setName] = useState("");
  const [scenario, setScenario] = useState<PilotScenarioType>("full_lifecycle");
  const [running, setRunning] = useState(false);

  const load = () => {
    setLoading(true);
    Promise.all([
      api.getPilotReadiness().then(setReadiness),
      api
        .getPilotDryRuns()
        .then((r) => setDryRuns(r.items))
        .catch(() => setDryRuns([])),
    ])
      .catch(() => {
        setReadiness(null);
        setErrored(true);
      })
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleRun = async () => {
    if (running) return;
    setRunning(true);
    try {
      const result = await api.createPilotDryRun({
        name: name.trim() || `Pilot dry-run ${new Date().toISOString().slice(0, 16)}`,
        scenarioType: scenario,
      });
      toast.success(`Internal dry-run recorded: ${result.status}.`);
      setName("");
      load();
    } catch (err) {
      if (isApiError(err)) {
        toast.error(`Dry-run failed (HTTP ${err.httpStatus}).`);
      } else {
        toast.error("Dry-run failed. Please retry.");
      }
    } finally {
      setRunning(false);
    }
  };

  if (loading) {
    return (
      <div className="h-96 grid place-items-center text-muted-foreground">
        Loading pilot readiness...
      </div>
    );
  }

  if (errored || !readiness) {
    return (
      <div data-testid="pilot-readiness-page">
        <PageHeader eyebrow="Operations" title="Controlled Internal Pilot Readiness" />
        <div
          data-testid="pilot-readiness-error"
          className="surface-elevated p-6 text-destructive text-[14px]"
        >
          Could not load pilot readiness. Please retry.
        </div>
      </div>
    );
  }

  const safety = readiness.safety;

  return (
    <div data-testid="pilot-readiness-page">
      <PageHeader
        eyebrow="Operations"
        title="Controlled Internal Pilot Readiness"
        description="Review end-to-end pilot readiness and run an internal dry-run. Dry-run only — no live provider action is triggered."
      />

      {/* Safety banner */}
      <div
        data-testid="pilot-safety-copy"
        className="mb-6 flex items-start gap-2 rounded-xl border border-border bg-muted/40 px-4 py-3 text-[13px] text-muted-foreground"
      >
        <ShieldCheck className="h-4 w-4 mt-0.5 shrink-0 text-success" />
        <span>
          Dry-run / readiness mode only — this page does NOT send WhatsApp, take
          a payment, book a shipment, place a call, or invoke any AI provider.
          Live provider actions are locked behind a future Director live gate.
        </span>
      </div>

      {/* Safety chips */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <Chip label="AI" value={safety.aiPaused ? "Paused" : "Running"} tone={safety.aiPaused ? "success" : "warning"} />
        <Chip label="Sandbox" value={safety.sandboxOn ? "ON" : "OFF"} tone="success" />
        <Chip label="Sync" value={safety.syncLive ? "Live" : "Offline"} tone="success" />
        <Chip label="Live provider actions" value={safety.providerLiveActionsLocked ? "Locked" : "Open"} tone={safety.providerLiveActionsLocked ? "success" : "danger"} />
      </div>

      {/* Pilot gate matrix */}
      <div className="surface-elevated p-6 mb-6">
        <h2 className="font-display text-lg font-semibold flex items-center gap-2 mb-4">
          <ClipboardCheck className="h-5 w-5 text-accent" /> Pilot gate matrix
        </h2>
        <div className="overflow-x-auto">
          <table data-testid="pilot-gate-matrix" className="w-full text-[13.5px] border-collapse">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-muted-foreground border-b border-border">
                <th className="py-2 pr-3">Gate</th>
                <th className="py-2 pr-3">Status</th>
                <th className="py-2 pr-3">Detail</th>
              </tr>
            </thead>
            <tbody>
              {readiness.gates.map((g) => (
                <GateRow key={g.key} gate={g} />
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Run dry-run */}
      <div className="surface-elevated p-6 mb-6" data-testid="pilot-run-form">
        <h3 className="font-display text-lg font-semibold flex items-center gap-2 mb-3">
          <PlayCircle className="h-5 w-5 text-accent" /> End-to-end dry run
        </h3>
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[200px]">
            <label className="text-[11px] uppercase tracking-wider text-muted-foreground">Name</label>
            <Input
              data-testid="pilot-run-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={running}
              placeholder="e.g. Joint pain pilot readiness"
            />
          </div>
          <div>
            <label className="text-[11px] uppercase tracking-wider text-muted-foreground block">Scenario</label>
            <select
              data-testid="pilot-run-scenario"
              aria-label="Scenario"
              value={scenario}
              onChange={(e) => setScenario(e.target.value as PilotScenarioType)}
              className="h-10 rounded-md border border-input bg-background px-3 text-[13.5px]"
            >
              {SCENARIOS.map((s) => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
          </div>
          <Button data-testid="pilot-run-button" onClick={handleRun} disabled={running}>
            {running ? "Running…" : "Run internal dry-run"}
          </Button>
        </div>
        <p className="text-[11px] text-muted-foreground mt-2">
          The dry-run evaluates readiness only. It never triggers a provider and
          always records live provider actions as blocked.
        </p>
      </div>

      {/* Blocked live actions */}
      <div className="surface-elevated p-6 mb-6">
        <h3 className="font-display text-lg font-semibold flex items-center gap-2 mb-3">
          <Lock className="h-5 w-5 text-destructive" /> Blocked live actions
        </h3>
        <ul className="space-y-1.5 text-[13px] text-muted-foreground list-disc pl-5">
          {readiness.blockedLiveActions.map((r, idx) => (
            <li key={idx}>{r}</li>
          ))}
        </ul>
      </div>

      {/* Director sign-off checklist (reference) */}
      <div className="surface-elevated p-6 mb-6">
        <h3 className="font-display text-lg font-semibold flex items-center gap-2 mb-3">
          <CheckCircle2 className="h-5 w-5 text-primary" /> Director sign-off checklist
        </h3>
        <ul className="grid sm:grid-cols-2 gap-2 text-[13px] text-muted-foreground">
          {readiness.signoffChecklistKeys.map((c) => (
            <li key={c.key} className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-border" /> {c.label}
            </li>
          ))}
        </ul>
      </div>

      {/* Recent dry-runs */}
      <div className="surface-elevated p-6">
        <h3 className="font-display text-lg font-semibold mb-3">Recent dry-runs ({dryRuns.length})</h3>
        {dryRuns.length === 0 ? (
          <p data-testid="pilot-dry-runs-empty" className="text-muted-foreground text-[14px]">
            No dry-runs yet. Run one above.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table data-testid="pilot-dry-runs-table" className="w-full text-[13.5px] border-collapse">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-muted-foreground border-b border-border">
                  <th className="py-2 pr-3">Name</th>
                  <th className="py-2 pr-3">Scenario</th>
                  <th className="py-2 pr-3">Status</th>
                  <th className="py-2 pr-3">By</th>
                </tr>
              </thead>
              <tbody>
                {dryRuns.map((d) => (
                  <tr key={d.id} className="border-b border-border/60 last:border-0">
                    <td className="py-2 pr-3 font-medium">{d.name}</td>
                    <td className="py-2 pr-3">{d.scenarioType.replace(/_/g, " ")}</td>
                    <td className="py-2 pr-3">
                      <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase ${GATE_STYLES[d.status] ?? GATE_STYLES.skipped}`}>
                        {d.status}
                      </span>
                    </td>
                    <td className="py-2 pr-3 text-muted-foreground">{d.createdBy ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
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
      <td className="py-2 pr-3 font-medium">{gate.label}</td>
      <td className="py-2 pr-3">
        <span
          data-testid={`pilot-gate-${gate.key}`}
          className={`rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase ${GATE_STYLES[gate.status] ?? GATE_STYLES.skipped}`}
        >
          {gate.status === "blocked" && <AlertTriangle className="inline h-3 w-3 mr-1" />}
          {gate.status}
        </span>
      </td>
      <td className="py-2 pr-3 text-muted-foreground text-[12.5px]">{gate.detail}</td>
    </tr>
  );
}
