import { useEffect, useState } from "react";
import {
  AlarmCheck,
  AlarmClock,
  CheckCircle2,
  CircleSlash,
  Clock,
  IndianRupee,
  Server,
  Shuffle,
  Sparkles,
  XCircle,
} from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { api } from "@/services/api";
import type { AgentRun, AiSchedulerStatus } from "@/types/domain";

function fmtTime(slot: { hour: number; minute: number }) {
  const h = String(slot.hour).padStart(2, "0");
  const m = String(slot.minute).padStart(2, "0");
  return `${h}:${m}`;
}

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

function StateRow({
  label,
  value,
  ok,
  hint,
}: {
  label: string;
  value: string;
  ok?: boolean;
  hint?: string;
}) {
  return (
    <div className="flex items-start justify-between gap-3 py-3 border-b border-border/60 last:border-0">
      <div>
        <div className="text-[13px] text-muted-foreground">{label}</div>
        <div className="font-medium text-foreground mt-0.5 break-all">{value}</div>
        {hint && <div className="text-xs text-muted-foreground mt-1">{hint}</div>}
      </div>
      {ok !== undefined && (
        <span
          className={
            "flex shrink-0 items-center gap-1.5 text-xs font-medium " +
            (ok ? "text-success" : "text-warning")
          }
        >
          {ok ? <CheckCircle2 className="h-4 w-4" /> : <CircleSlash className="h-4 w-4" />}
          {ok ? "Ready" : "Pending"}
        </span>
      )}
    </div>
  );
}

function RunCard({
  title,
  icon: Icon,
  run,
}: {
  title: string;
  icon: typeof AlarmClock;
  run: AgentRun | null;
}) {
  return (
    <div className="surface-card p-5">
      <div className="flex items-center gap-2 mb-3">
        <Icon className="h-4 w-4 text-accent" />
        <h3 className="font-display text-base font-semibold">{title}</h3>
      </div>
      {run ? (
        <div className="space-y-1.5 text-sm">
          <div className="flex items-center gap-2">
            <StatusPill
              tone={
                run.status === "success"
                  ? "success"
                  : run.status === "failed"
                  ? "danger"
                  : run.status === "skipped"
                  ? "info"
                  : "neutral"
              }
            >
              {run.status}
            </StatusPill>
            <span className="text-muted-foreground text-xs font-mono">{run.id}</span>
          </div>
          <div className="text-muted-foreground">
            <span className="text-foreground font-medium">{run.provider}</span>
            {run.model && <> · {run.model}</>}
          </div>
          <div className="text-muted-foreground">
            <Clock className="h-3.5 w-3.5 inline mr-1" />
            {fmtRelative(run.completedAt ?? run.createdAt)} · {run.latencyMs}ms
          </div>
          {run.totalTokens != null && (
            <div className="text-muted-foreground">
              tokens: {run.totalTokens.toLocaleString()}
              {run.costUsd && (
                <>
                  {" · "}
                  <IndianRupee className="h-3.5 w-3.5 inline" />
                  {Number(run.costUsd).toFixed(4)} USD
                </>
              )}
            </div>
          )}
          {run.fallbackUsed && (
            <div className="text-warning text-xs flex items-center gap-1">
              <Shuffle className="h-3.5 w-3.5" />
              Fallback used (provider drift)
            </div>
          )}
          {run.errorMessage && (
            <div className="mt-2 rounded-md bg-destructive/5 border border-destructive/20 px-3 py-2 text-xs text-destructive">
              <XCircle className="h-3 w-3 inline mr-1" />
              {run.errorMessage}
            </div>
          )}
        </div>
      ) : (
        <div className="text-sm text-muted-foreground">Never run.</div>
      )}
    </div>
  );
}

export default function Scheduler() {
  const [status, setStatus] = useState<AiSchedulerStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getAiSchedulerStatus()
      .then((data) => {
        if (!cancelled) setStatus(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load scheduler status.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <>
      <PageHeader
        eyebrow="AI Layer · Phase 3C"
        title="AI Scheduler & Cost"
        description="Celery beat schedules the daily CEO briefing + CAIO sweep at 09:00 and 18:00 IST. The dispatcher walks the provider fallback chain (OpenAI → Anthropic) and stamps token usage + USD cost on every AgentRun."
      />

      {error && (
        <div className="mb-4 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="grid lg:grid-cols-2 gap-6 mb-6">
        <div className="surface-card p-6">
          <div className="flex items-center gap-2 mb-4">
            <Server className="h-5 w-5 text-accent" />
            <h2 className="font-display text-lg font-semibold">Runtime configuration</h2>
          </div>
          <StateRow
            label="Celery configured"
            value={status?.celeryConfigured ? "Yes" : "No"}
            ok={!!status?.celeryConfigured}
          />
          <StateRow
            label="Celery eager mode"
            value={status?.celeryEagerMode ? "On (synchronous, no Redis)" : "Off (worker required)"}
            hint="Local dev defaults to eager. Production worker flips this off."
          />
          <StateRow
            label="Redis configured"
            value={status?.brokerUrl ?? "—"}
            ok={!!status?.redisConfigured}
            hint="Local Redis: docker compose -f docker-compose.dev.yml up -d redis"
          />
          <StateRow label="Timezone" value={status?.timezone ?? "Asia/Kolkata"} />
        </div>

        <div className="surface-card p-6">
          <div className="flex items-center gap-2 mb-4">
            <AlarmClock className="h-5 w-5 text-accent" />
            <h2 className="font-display text-lg font-semibold">Daily briefing schedule</h2>
          </div>
          <StateRow
            label="Morning slot"
            value={status ? `${fmtTime(status.morningSchedule)} ${status.timezone}` : "—"}
            hint="CEO briefing + CAIO sweep"
          />
          <StateRow
            label="Evening slot"
            value={status ? `${fmtTime(status.eveningSchedule)} ${status.timezone}` : "—"}
            hint="CEO recap + CAIO sweep"
          />
          <div className="mt-3 rounded-xl bg-muted/30 p-3 text-xs text-muted-foreground">
            Manual override: <code className="font-mono">python manage.py run_daily_ai_briefing</code>
          </div>
        </div>
      </div>

      <div className="surface-card p-6 mb-6">
        <div className="flex items-center gap-2 mb-4">
          <Sparkles className="h-5 w-5 text-accent" />
          <h2 className="font-display text-lg font-semibold">AI provider chain</h2>
        </div>
        <div className="grid sm:grid-cols-2 gap-4">
          <StateRow
            label="Primary provider"
            value={status?.aiProvider ?? "—"}
            hint={
              status?.aiProvider === "disabled"
                ? "Every run will be skipped — no LLM dispatch"
                : "Active"
            }
          />
          <StateRow label="Primary model" value={status?.primaryModel || "—"} />
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <span className="text-xs uppercase tracking-wider text-muted-foreground">
            Fallback order
          </span>
          {status?.fallbacks.map((p, i) => (
            <span key={p} className="flex items-center gap-1 text-sm">
              <StatusPill tone={i === 0 ? "info" : "neutral"}>{p}</StatusPill>
              {i < (status?.fallbacks.length ?? 0) - 1 && (
                <span className="text-muted-foreground">→</span>
              )}
            </span>
          ))}
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-6 mb-6">
        <RunCard
          title="Last CEO daily briefing"
          icon={Sparkles}
          run={status?.lastDailyBriefingRun ?? null}
        />
        <RunCard
          title="Last CAIO audit sweep"
          icon={AlarmCheck}
          run={status?.lastCaioSweepRun ?? null}
        />
      </div>

      <div className="surface-card p-6">
        <div className="flex items-center gap-2 mb-4">
          <IndianRupee className="h-5 w-5 text-accent" />
          <h2 className="font-display text-lg font-semibold">Last successful run · cost & fallback</h2>
        </div>
        <div className="grid sm:grid-cols-2 gap-4">
          <StateRow
            label="Last cost (USD)"
            value={status?.lastCostUsd ? `$${Number(status.lastCostUsd).toFixed(6)}` : "—"}
            hint="Model-wise pricing snapshot stored on each AgentRun"
          />
          <StateRow
            label="Last fallback used"
            value={status?.lastFallbackUsed ? "Yes — secondary provider answered" : "No — primary"}
            ok={status?.lastFallbackUsed === false}
          />
        </div>
      </div>
    </>
  );
}
