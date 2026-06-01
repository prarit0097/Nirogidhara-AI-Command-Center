import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { api, isApiError } from "@/services/api";
import type {
  PilotExecutionSummary,
  PilotPlan,
  PilotTask,
  PilotTaskAction,
} from "@/types/domain";
import {
  AlertTriangle,
  ClipboardList,
  ListChecks,
  Lock,
  ShieldCheck,
  Users,
} from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

const STATUS_STYLES: Record<string, string> = {
  todo: "bg-muted text-muted-foreground",
  in_progress: "bg-primary/15 text-primary",
  blocked: "bg-destructive/15 text-destructive",
  done: "bg-success/15 text-success",
  skipped: "bg-warning/20 text-warning",
  cancelled: "bg-destructive/15 text-destructive",
};

const TEAM_LABELS: Record<string, string> = {
  calling_agent: "Calling",
  confirmation_team: "Confirmation",
  warehouse_dispatch: "Dispatch / Warehouse",
  delivery_rto: "Delivery / RTO",
  qa_compliance: "QA / Compliance",
  finance_accounts: "Finance / Accounts",
  director_admin: "Director / Admin",
};

// Internal-only task actions — change ONLY the internal task record state.
const TASK_ACTIONS: { action: PilotTaskAction; label: string; from: string[] }[] = [
  { action: "start", label: "Start", from: ["todo"] },
  { action: "block", label: "Block", from: ["in_progress"] },
  { action: "unblock", label: "Unblock", from: ["blocked"] },
  { action: "complete", label: "Complete", from: ["in_progress"] },
  { action: "skip", label: "Skip", from: ["todo", "in_progress", "blocked"] },
  { action: "cancel", label: "Cancel", from: ["todo", "in_progress", "blocked"] },
];

export default function PilotWorkbench() {
  const [plans, setPlans] = useState<PilotPlan[]>([]);
  const [planId, setPlanId] = useState<number | null>(null);
  const [summary, setSummary] = useState<PilotExecutionSummary | null>(null);
  const [tasks, setTasks] = useState<PilotTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [errored, setErrored] = useState(false);
  const [busy, setBusy] = useState(false);

  // Initial: load plans + global execution summary.
  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.getPilotPlans().then((r) => setPlans(r.items)).catch(() => setPlans([])),
      api.getPilotExecutionSummary().then(setSummary),
    ])
      .catch(() => {
        setSummary(null);
        setErrored(true);
      })
      .finally(() => setLoading(false));
  }, []);

  const loadPlan = (id: number) => {
    setPlanId(id);
    Promise.all([
      api.getPilotExecutionSummary(id).then(setSummary).catch(() => {}),
      api.getPilotPlanTasks(id).then((r) => setTasks(r.items)).catch(() => setTasks([])),
    ]);
  };

  const refresh = () => {
    if (planId == null) return;
    loadPlan(planId);
  };

  const handleGenerate = async () => {
    if (planId == null || busy) return;
    setBusy(true);
    try {
      const res = await api.generatePilotTasks(planId);
      toast.success(`Generated ${res.created} internal task(s).`);
      loadPlan(planId);
    } catch (err) {
      if (isApiError(err)) {
        toast.error(
          err.httpStatus === 409
            ? "Plan must be approved_internal or running_internal first."
            : `Generate failed (HTTP ${err.httpStatus}).`,
        );
      } else {
        toast.error("Generate failed. Please retry.");
      }
    } finally {
      setBusy(false);
    }
  };

  const handleTransition = async (task: PilotTask, action: PilotTaskAction) => {
    if (busy) return;
    setBusy(true);
    try {
      let note = "";
      if (action === "block") note = "Blocked (internal)";
      await api.transitionPilotTask(task.id, { action, note });
      toast.success(`Task: ${action}.`);
      refresh();
    } catch (err) {
      if (isApiError(err)) {
        toast.error(
          err.httpStatus === 409
            ? "That transition is not allowed from the current status."
            : `Transition failed (HTTP ${err.httpStatus}).`,
        );
      } else {
        toast.error("Transition failed. Please retry.");
      }
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="h-96 grid place-items-center text-muted-foreground">
        Loading pilot execution workbench...
      </div>
    );
  }

  if (errored || !summary) {
    return (
      <div data-testid="pilot-workbench-page">
        <PageHeader eyebrow="Operations" title="Internal Pilot Execution Workbench" />
        <div
          data-testid="pilot-workbench-error"
          className="surface-elevated p-6 text-destructive text-[14px]"
        >
          Could not load the pilot execution workbench. Please retry.
        </div>
      </div>
    );
  }

  const safety = summary.safety;

  return (
    <div data-testid="pilot-workbench-page">
      <PageHeader
        eyebrow="Operations"
        title="Internal Pilot Execution Workbench"
        description="Convert an approved internal pilot plan into role-based task queues and track execution — internal control only, no live provider automation."
      />

      {/* Safety banner */}
      <div
        data-testid="pilot-workbench-safety-copy"
        className="mb-6 flex items-start gap-2 rounded-xl border border-border bg-muted/40 px-4 py-3 text-[13px] text-muted-foreground"
      >
        <ShieldCheck className="h-4 w-4 mt-0.5 shrink-0 text-success" />
        <span>
          Internal control only — no live provider automation. Generating or
          progressing task queues here NEVER sends WhatsApp, takes a payment,
          books a shipment, places a call, or invokes any AI provider. Live
          provider actions stay locked behind a future Director live gate.
        </span>
      </div>

      {/* Safety chips */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <Chip label="AI" value={safety.aiPaused ? "Paused" : "Running"} tone={safety.aiPaused ? "success" : "warning"} />
        <Chip label="Sandbox" value={safety.sandboxOn ? "ON" : "OFF"} tone="success" />
        <Chip label="Sync" value={safety.syncLive ? "Live" : "Offline"} tone="success" />
        <Chip label="Live provider actions" value={safety.providerLiveActionsLocked ? "Locked" : "Open"} tone={safety.providerLiveActionsLocked ? "success" : "danger"} />
      </div>

      {/* Plan selector + generate */}
      <div className="surface-elevated p-6 mb-6" data-testid="pilot-workbench-plan-bar">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[220px]">
            <label className="text-[11px] uppercase tracking-wider text-muted-foreground block">Pilot plan</label>
            <select
              data-testid="pilot-workbench-plan-select"
              aria-label="Pilot plan"
              value={planId ?? ""}
              onChange={(e) => e.target.value && loadPlan(Number(e.target.value))}
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-[13.5px]"
            >
              <option value="">Select a pilot plan…</option>
              {plans.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.status.replace(/_/g, " ")})
                </option>
              ))}
            </select>
          </div>
          <Button
            data-testid="pilot-generate-button"
            onClick={handleGenerate}
            disabled={busy || planId == null}
          >
            Generate role-based task queues
          </Button>
        </div>
        <p className="text-[11px] text-muted-foreground mt-2">
          Generating queues never triggers a provider. Tasks are internal control
          records only and always record live provider actions as blocked.
        </p>
      </div>

      {/* Execution progress dashboard */}
      <div className="surface-elevated p-6 mb-6" data-testid="pilot-execution-dashboard">
        <h2 className="font-display text-lg font-semibold flex items-center gap-2 mb-4">
          <ListChecks className="h-5 w-5 text-accent" /> Execution progress
          <span className="ml-auto text-[13px] font-normal text-muted-foreground">
            Overall: {summary.overall.done}/{summary.overall.total} done ({summary.overall.progressPct}%)
          </span>
        </h2>
        {summary.byTeam.length === 0 ? (
          <p data-testid="pilot-exec-empty" className="text-muted-foreground text-[14px]">
            No tasks yet. Select an approved plan and generate role-based queues.
          </p>
        ) : (
          <div className="space-y-3" data-testid="pilot-team-progress">
            {summary.byTeam.map((t) => (
              <div key={t.teamRole}>
                <div className="flex items-center justify-between text-[12.5px] mb-1">
                  <span className="font-medium">{t.teamLabel}</span>
                  <span className="text-muted-foreground">
                    {t.done}/{t.total} done · {t.inProgress} active · {t.blocked} blocked
                  </span>
                </div>
                <div className="h-2 rounded-full bg-muted overflow-hidden">
                  <div className="h-full bg-success" style={{ width: `${t.progressPct}%` }} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Team queues */}
      {planId != null && (
        <div className="surface-elevated p-6 mb-6" data-testid="pilot-task-queues">
          <h3 className="font-display text-lg font-semibold flex items-center gap-2 mb-4">
            <Users className="h-5 w-5 text-accent" /> Role-based task queues
          </h3>
          {tasks.length === 0 ? (
            <p data-testid="pilot-tasks-empty" className="text-muted-foreground text-[14px]">
              No tasks for this plan yet. Use "Generate role-based task queues".
            </p>
          ) : (
            <div className="space-y-2">
              {tasks.map((task) => (
                <div
                  key={task.id}
                  data-testid={`pilot-task-${task.id}`}
                  className="rounded-lg border border-border bg-muted/20 px-3 py-2"
                >
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <div className="min-w-0">
                      <div className="font-medium truncate">{task.title}</div>
                      <div className="text-[12px] text-muted-foreground">
                        {TEAM_LABELS[task.teamRole] ?? task.teamRole} · {task.assignedTeamLabel || task.assignedTo || "unassigned"}
                      </div>
                    </div>
                    <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase ${STATUS_STYLES[task.status] ?? STATUS_STYLES.todo}`}>
                      {task.status === "blocked" && <AlertTriangle className="inline h-3 w-3 mr-1" />}
                      {task.status.replace(/_/g, " ")}
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {TASK_ACTIONS.filter((a) => a.from.includes(task.status)).map((a) => (
                      <Button
                        key={a.action}
                        data-testid={`pilot-task-${task.id}-${a.action}`}
                        variant="outline"
                        size="sm"
                        disabled={busy}
                        onClick={() => handleTransition(task, a.action)}
                      >
                        {a.label}
                      </Button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Blocked live actions */}
      <div className="surface-elevated p-6" data-testid="pilot-workbench-blocked">
        <h3 className="font-display text-lg font-semibold flex items-center gap-2 mb-3">
          <Lock className="h-5 w-5 text-destructive" /> Blocked live actions
        </h3>
        <ul className="space-y-1.5 text-[13px] text-muted-foreground list-disc pl-5">
          {summary.blockedLiveActions.map((r, idx) => (
            <li key={idx}>{r}</li>
          ))}
        </ul>
        <p className="text-[11px] text-muted-foreground mt-3 flex items-center gap-1.5">
          <ClipboardList className="h-3.5 w-3.5" /> Every task is internal/DB-only; live provider actions remain locked.
        </p>
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
