import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Gauge,
  Play,
  ShieldCheck,
  ShieldOff,
  RotateCcw,
  Sparkles,
  XCircle,
} from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { api } from "@/services/api";
import type {
  AgentBudget,
  AgentBudgetWritePayload,
  AgentName,
  PromptVersion,
  SandboxState,
} from "@/types/domain";

const AGENTS: AgentName[] = [
  "ceo",
  "caio",
  "ads",
  "rto",
  "sales_growth",
  "cfo",
  "compliance",
];

function fmtRelative(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.valueOf())) return iso;
  const diffMin = Math.round((Date.now() - d.valueOf()) / 60_000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin} min ago`;
  if (diffMin < 1440) return `${Math.round(diffMin / 60)}h ago`;
  return d.toLocaleString();
}

function pillToneForStatus(status: PromptVersion["status"]) {
  switch (status) {
    case "active":
      return "success";
    case "sandbox":
      return "info";
    case "draft":
      return "neutral";
    case "rolled_back":
      return "warning";
    case "archived":
      return "neutral";
    default:
      return "neutral";
  }
}

export default function Governance() {
  const [sandbox, setSandbox] = useState<SandboxState | null>(null);
  const [prompts, setPrompts] = useState<PromptVersion[]>([]);
  const [budgets, setBudgets] = useState<AgentBudget[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    try {
      const [s, p, b] = await Promise.all([
        api.getSandboxStatus(),
        api.listPromptVersions(),
        api.listAgentBudgets(),
      ]);
      setSandbox(s);
      setPrompts(p);
      setBudgets(b);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load governance.");
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const promptsByAgent = useMemo(() => {
    const map: Record<string, PromptVersion[]> = {};
    for (const pv of prompts) {
      (map[pv.agent] ||= []).push(pv);
    }
    return map;
  }, [prompts]);

  const budgetByAgent = useMemo(() => {
    const map: Record<string, AgentBudget> = {};
    for (const b of budgets) map[b.agent] = b;
    return map;
  }, [budgets]);

  const onToggleSandbox = async (next: boolean) => {
    setBusy(true);
    try {
      const updated = await api.setSandboxStatus({ isEnabled: next });
      setSandbox(updated);
      toast.success(`Sandbox mode ${next ? "enabled" : "disabled"}`);
    } catch (err) {
      toast.error("Sandbox toggle failed");
    } finally {
      setBusy(false);
    }
  };

  const onActivate = async (id: string) => {
    try {
      await api.activatePromptVersion(id);
      toast.success("Prompt version activated");
      await refresh();
    } catch {
      toast.error("Activate failed");
    }
  };

  const onRollback = async (id: string) => {
    const reason = window.prompt("Rollback reason?");
    if (!reason) return;
    try {
      await api.rollbackPromptVersion(id, reason);
      toast.success("Rolled back");
      await refresh();
    } catch {
      toast.error("Rollback failed");
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="AI Layer · Phase 3D"
        title="AI Governance — Sandbox · Prompts · Budgets"
        description="Sandbox toggle gates AI suggestions from touching the live CEO briefing. Versioned prompts let you roll back instantly. Per-agent USD budgets block costly runs before they dispatch."
      />

      {error && (
        <div className="mb-4 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Sandbox card */}
      <div className="surface-card p-6 mb-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            {sandbox?.isEnabled ? (
              <ShieldCheck className="h-6 w-6 text-info mt-0.5" />
            ) : (
              <ShieldOff className="h-6 w-6 text-muted-foreground mt-0.5" />
            )}
            <div>
              <h2 className="font-display text-lg font-semibold">Sandbox mode</h2>
              <p className="text-sm text-muted-foreground mt-1 max-w-2xl">
                {sandbox?.isEnabled
                  ? "Sandbox is ON. Successful AgentRuns will NOT refresh the live CeoBriefing. CAIO is read-only as always."
                  : "Sandbox is OFF. Successful CEO runs refresh the live briefing. Flip on when testing new prompt versions or providers."}
              </p>
              {sandbox && (
                <div className="text-xs text-muted-foreground mt-2">
                  Last updated {fmtRelative(sandbox.updatedAt)}
                  {sandbox.updatedBy && <> by {sandbox.updatedBy}</>}
                </div>
              )}
            </div>
          </div>
          <div className="flex flex-col items-end gap-2">
            <StatusPill tone={sandbox?.isEnabled ? "info" : "neutral"}>
              {sandbox?.isEnabled ? "ON" : "OFF"}
            </StatusPill>
            <Switch
              checked={!!sandbox?.isEnabled}
              disabled={busy}
              onCheckedChange={onToggleSandbox}
              aria-label="Toggle sandbox mode"
            />
          </div>
        </div>
      </div>

      {/* Per-agent prompt versions + budgets */}
      <div className="space-y-6">
        {AGENTS.map((agent) => {
          const list = promptsByAgent[agent] ?? [];
          const active = list.find((p) => p.isActive);
          const budget = budgetByAgent[agent];
          return (
            <div key={agent} className="surface-card p-6">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-5 w-5 text-accent" />
                  <h3 className="font-display text-lg font-semibold capitalize">
                    {agent.replace("_", " ")} agent
                  </h3>
                </div>
                {active ? (
                  <StatusPill tone="success">
                    Active · {active.version}
                  </StatusPill>
                ) : (
                  <StatusPill tone="neutral">No active prompt</StatusPill>
                )}
              </div>

              {/* Budget row */}
              <BudgetRow agent={agent} budget={budget} onSaved={refresh} />

              {/* Prompt versions */}
              <div className="mt-5 border-t border-border/60 pt-5">
                <div className="text-xs uppercase tracking-wider text-muted-foreground mb-3">
                  Prompt versions
                </div>
                {list.length === 0 ? (
                  <div className="text-sm text-muted-foreground">
                    No versions yet. Use the API to seed a draft.
                  </div>
                ) : (
                  <ul className="space-y-2">
                    {list.map((pv) => (
                      <li
                        key={pv.id}
                        className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border/60 bg-muted/20 px-4 py-3 text-sm"
                      >
                        <div>
                          <div className="font-medium">
                            <span className="font-mono text-xs text-muted-foreground mr-2">
                              {pv.id}
                            </span>
                            v{pv.version}
                            {pv.title && (
                              <span className="text-muted-foreground"> · {pv.title}</span>
                            )}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            Created {fmtRelative(pv.createdAt)}
                            {pv.createdBy && <> by {pv.createdBy}</>}
                            {pv.rollbackReason && (
                              <> · rollback reason: {pv.rollbackReason}</>
                            )}
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <StatusPill tone={pillToneForStatus(pv.status)}>
                            {pv.status}
                          </StatusPill>
                          {!pv.isActive && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => onActivate(pv.id)}
                            >
                              <Play className="h-3.5 w-3.5 mr-1" /> Activate
                            </Button>
                          )}
                          {pv.isActive && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => onRollback(pv.id)}
                            >
                              <RotateCcw className="h-3.5 w-3.5 mr-1" /> Rollback
                            </Button>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="surface-card p-6 mt-6 bg-gradient-emerald-soft">
        <div className="flex items-start gap-3">
          <Gauge className="h-5 w-5 text-accent mt-0.5" />
          <div className="text-sm text-muted-foreground">
            <strong className="text-foreground">Compliance reminder.</strong>{" "}
            PromptVersion rows cannot bypass the Approved Claim Vault — every
            prompt still attaches the relevant <code>apps.compliance.Claim</code>{" "}
            entries on top of any custom system policy. CAIO remains read-only
            in every state. Budget blocks fail closed and never trigger the
            provider fallback chain.
          </div>
        </div>
      </div>
    </>
  );
}

function BudgetRow({
  agent,
  budget,
  onSaved,
}: {
  agent: AgentName;
  budget: AgentBudget | undefined;
  onSaved: () => Promise<void> | void;
}) {
  const [daily, setDaily] = useState<string>(budget?.dailyBudgetUsd ?? "0");
  const [monthly, setMonthly] = useState<string>(budget?.monthlyBudgetUsd ?? "0");
  const [enforced, setEnforced] = useState<boolean>(budget?.isEnforced ?? true);
  const [threshold, setThreshold] = useState<number>(
    budget?.alertThresholdPct ?? 80,
  );
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (budget) {
      setDaily(budget.dailyBudgetUsd);
      setMonthly(budget.monthlyBudgetUsd);
      setEnforced(budget.isEnforced);
      setThreshold(budget.alertThresholdPct);
    }
  }, [budget]);

  const save = async () => {
    setSaving(true);
    try {
      const payload: AgentBudgetWritePayload = {
        agent,
        dailyBudgetUsd: daily || "0",
        monthlyBudgetUsd: monthly || "0",
        isEnforced: enforced,
        alertThresholdPct: threshold,
      };
      await api.upsertAgentBudget(payload);
      toast.success("Budget saved");
      await onSaved();
    } catch {
      toast.error("Save failed");
    } finally {
      setSaving(false);
    }
  };

  const dailySpend = budget?.dailySpendUsd ?? "0";
  const monthlySpend = budget?.monthlySpendUsd ?? "0";

  return (
    <div className="grid md:grid-cols-2 gap-4">
      <div className="space-y-3">
        <div className="text-xs uppercase tracking-wider text-muted-foreground">
          Budget
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="text-xs">Daily budget (USD)</Label>
            <Input
              value={daily}
              onChange={(e) => setDaily(e.target.value)}
              inputMode="decimal"
            />
          </div>
          <div>
            <Label className="text-xs">Monthly budget (USD)</Label>
            <Input
              value={monthly}
              onChange={(e) => setMonthly(e.target.value)}
              inputMode="decimal"
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="text-xs">Alert threshold (%)</Label>
            <Input
              type="number"
              min={0}
              max={100}
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
            />
          </div>
          <div className="flex items-end gap-2">
            <Switch
              checked={enforced}
              onCheckedChange={setEnforced}
              id={`enforce-${agent}`}
            />
            <Label htmlFor={`enforce-${agent}`} className="text-xs">
              Enforce (block when exceeded)
            </Label>
          </div>
        </div>
        <Button size="sm" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save budget"}
        </Button>
      </div>

      <div className="space-y-2 rounded-xl bg-muted/30 p-4 text-sm">
        <div className="text-xs uppercase tracking-wider text-muted-foreground">
          Current spend (USD)
        </div>
        <div className="flex items-center justify-between">
          <span>Today</span>
          <span className="font-medium">${Number(dailySpend).toFixed(4)}</span>
        </div>
        <div className="flex items-center justify-between">
          <span>This month</span>
          <span className="font-medium">${Number(monthlySpend).toFixed(4)}</span>
        </div>
        <div className="text-xs text-muted-foreground pt-2">
          Computed from successful AgentRun rows; budget block will fail closed
          and never trigger provider fallback.
        </div>
      </div>
    </div>
  );
}
