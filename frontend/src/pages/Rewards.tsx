import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { api } from "@/services/api";
import type {
  RewardPenalty,
  RewardPenaltyEvent,
  RewardPenaltySummary,
} from "@/types/domain";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Award,
  Clock,
  Loader2,
  Minus,
  Plus,
  RefreshCw,
  Trophy,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

const REWARD_TRIGGERS = [
  "Delivered order",
  "Net delivered profit",
  "Advance payment",
  "Customer satisfaction",
  "Reorder potential",
  "Compliance safety",
];
const PENALTY_TRIGGERS = [
  "Bad lead quality",
  "Weak closing",
  "Wrong address",
  "Missed delivery reminder",
  "Risky claim",
  "RTO risk ignored",
  "Over-discount",
];

function formatTimestamp(value: string | null | undefined) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

export default function Rewards() {
  const [leaderboard, setLeaderboard] = useState<RewardPenalty[]>([]);
  const [events, setEvents] = useState<RewardPenaltyEvent[]>([]);
  const [summary, setSummary] = useState<RewardPenaltySummary | null>(null);
  const [sweeping, setSweeping] = useState(false);
  const [sweepError, setSweepError] = useState<string | null>(null);

  useEffect(() => {
    api.getRewardPenaltyScores().then(setLeaderboard);
    api.getRewardPenaltyEvents({ limit: 200 }).then(setEvents);
    api.getRewardPenaltySummary().then(setSummary);
  }, []);

  async function runSweep(dryRun: boolean) {
    setSweeping(true);
    setSweepError(null);
    try {
      await api.runRewardPenaltySweep({ dryRun });
      // Refresh derived views.
      const [nextLeaderboard, nextEvents, nextSummary] = await Promise.all([
        api.getRewardPenaltyScores(),
        api.getRewardPenaltyEvents({ limit: 200 }),
        api.getRewardPenaltySummary(),
      ]);
      setLeaderboard(nextLeaderboard);
      setEvents(nextEvents);
      setSummary(nextSummary);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Sweep failed";
      setSweepError(message);
    } finally {
      setSweeping(false);
    }
  }

  const totalReward = summary?.totalReward ?? 0;
  const totalPenalty = summary?.totalPenalty ?? 0;
  const netScore = summary?.netScore ?? totalReward - totalPenalty;
  const evaluatedOrders = summary?.evaluatedOrders ?? events.length;
  const lastSweepAt = summary?.lastSweepAt;
  const missingWarnings = summary?.missingDataWarnings ?? [];

  const topRewarded = useMemo(
    () =>
      [...leaderboard].sort((a, b) => b.reward - a.reward).slice(0, 1)[0] ?? null,
    [leaderboard],
  );
  const topPenalized = useMemo(
    () =>
      [...leaderboard].sort((a, b) => b.penalty - a.penalty).slice(0, 1)[0] ?? null,
    [leaderboard],
  );

  return (
    <>
      <PageHeader
        eyebrow="Governance · Phase 4B"
        title="Reward & Penalty Engine"
        description="Score AI agents only. CEO AI always receives net accountability for every delivered, RTO, or cancelled order."
      />

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <div className="surface-card p-5 border-l-4 border-l-success">
          <div className="flex items-center gap-2 text-success">
            <Plus className="h-4 w-4" />
            <span className="text-xs uppercase tracking-wider font-semibold">
              Reward total
            </span>
          </div>
          <div className="font-display text-3xl font-semibold mt-1">
            +{totalReward}
          </div>
          {topRewarded && (
            <div className="text-xs text-muted-foreground mt-1">
              Top: {topRewarded.name}
            </div>
          )}
        </div>
        <div className="surface-card p-5 border-l-4 border-l-destructive">
          <div className="flex items-center gap-2 text-destructive">
            <Minus className="h-4 w-4" />
            <span className="text-xs uppercase tracking-wider font-semibold">
              Penalty total
            </span>
          </div>
          <div className="font-display text-3xl font-semibold mt-1">
            −{totalPenalty}
          </div>
          {topPenalized && (
            <div className="text-xs text-muted-foreground mt-1">
              Top: {topPenalized.name}
            </div>
          )}
        </div>
        <div className="surface-card p-5 border-l-4 border-l-accent">
          <div className="flex items-center gap-2 text-accent-foreground">
            <Trophy className="h-4 w-4 text-accent" />
            <span className="text-xs uppercase tracking-wider font-semibold">
              Net AI score
            </span>
          </div>
          <div className="font-display text-3xl font-semibold mt-1 gold-text">
            {netScore}
          </div>
          <div className="text-xs text-muted-foreground mt-1">
            {evaluatedOrders} orders evaluated
          </div>
        </div>
        <div className="surface-card p-5">
          <div className="flex items-center gap-2 text-muted-foreground">
            <Clock className="h-4 w-4" />
            <span className="text-xs uppercase tracking-wider font-semibold">
              Last sweep
            </span>
          </div>
          <div className="font-display text-base font-medium mt-1">
            {formatTimestamp(lastSweepAt)}
          </div>
          <div className="flex gap-2 mt-3">
            <Button
              size="sm"
              onClick={() => runSweep(false)}
              disabled={sweeping}
              className="bg-primary text-primary-foreground"
            >
              {sweeping ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              <span className="ml-1.5">Run sweep</span>
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => runSweep(true)}
              disabled={sweeping}
            >
              Dry run
            </Button>
          </div>
          {sweepError && (
            <div className="text-xs text-destructive mt-2">{sweepError}</div>
          )}
        </div>
      </div>

      <div className="surface-card p-6 mb-6 bg-gradient-emerald-soft">
        <h3 className="font-display text-lg font-semibold mb-2 flex items-center gap-2">
          <Award className="h-5 w-5 text-accent" />
          Net Delivered Profit formula
        </h3>
        <code className="block text-sm bg-background/70 rounded-lg p-3 font-mono">
          Delivered Revenue − Ad Cost − Discount − Courier Cost − RTO Loss − Payment Gateway Charges − Product Cost
        </code>
        <p className="text-xs text-muted-foreground mt-3">
          Phase 4B scope: AI agents only. CAIO is audit-only. Human staff scoring lands later.
        </p>
      </div>

      <div className="grid xl:grid-cols-[1.4fr_1fr] gap-6 mb-6">
        <div className="surface-card p-6">
          <h3 className="font-display text-lg font-semibold mb-3">
            Agent leaderboard
          </h3>
          <ResponsiveContainer width="100%" height={340}>
            <BarChart
              data={leaderboard.slice(0, 10)}
              layout="vertical"
              margin={{ left: 4 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="hsl(var(--border))"
                horizontal={false}
              />
              <XAxis
                type="number"
                stroke="hsl(var(--muted-foreground))"
                fontSize={11}
              />
              <YAxis
                type="category"
                dataKey="name"
                stroke="hsl(var(--muted-foreground))"
                fontSize={11}
                width={170}
              />
              <Tooltip
                contentStyle={{
                  borderRadius: 12,
                  border: "1px solid hsl(var(--border))",
                  fontSize: 12,
                }}
              />
              <Bar dataKey="reward" stackId="a" fill="hsl(var(--success))" />
              <Bar dataKey="penalty" stackId="a" fill="hsl(var(--destructive))" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="space-y-4">
          <div className="surface-card p-5">
            <h4 className="font-medium mb-2 text-success">Reward triggers</h4>
            <div className="flex flex-wrap gap-1.5">
              {REWARD_TRIGGERS.map((r) => (
                <StatusPill key={r} tone="success">
                  {r}
                </StatusPill>
              ))}
            </div>
          </div>
          <div className="surface-card p-5">
            <h4 className="font-medium mb-2 text-destructive">Penalty triggers</h4>
            <div className="flex flex-wrap gap-1.5">
              {PENALTY_TRIGGERS.map((p) => (
                <StatusPill key={p} tone="danger">
                  {p}
                </StatusPill>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="surface-card overflow-hidden mb-6">
        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
          <h3 className="font-display text-lg font-semibold">
            Agent-wise leaderboard
          </h3>
          <span className="text-xs text-muted-foreground">
            {leaderboard.length} AI agents
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[820px]">
            <thead className="bg-muted/30 text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left font-medium px-6 py-3">Agent</th>
                <th className="text-left font-medium py-3">Type</th>
                <th className="text-right font-medium py-3">Reward</th>
                <th className="text-right font-medium py-3">Penalty</th>
                <th className="text-right font-medium py-3">Net</th>
                <th className="text-right font-medium py-3">+ Orders</th>
                <th className="text-right font-medium py-3">− Orders</th>
                <th className="text-right font-medium px-6 py-3">Last calculated</th>
              </tr>
            </thead>
            <tbody>
              {leaderboard.map((r) => (
                <tr key={r.name} className="border-t border-border/60 hover:bg-muted/20">
                  <td className="px-6 py-3 font-medium">{r.name}</td>
                  <td className="py-3 text-xs text-muted-foreground capitalize">
                    {r.agentType ?? "—"}
                  </td>
                  <td className="py-3 text-right text-success font-semibold tabular-nums">
                    +{r.reward}
                  </td>
                  <td className="py-3 text-right text-destructive font-semibold tabular-nums">
                    −{r.penalty}
                  </td>
                  <td className="py-3 text-right font-semibold tabular-nums">{r.net}</td>
                  <td className="py-3 text-right tabular-nums">{r.rewardedOrders ?? 0}</td>
                  <td className="py-3 text-right tabular-nums">{r.penalizedOrders ?? 0}</td>
                  <td className="px-6 py-3 text-right text-xs text-muted-foreground">
                    {formatTimestamp(r.lastCalculatedAt)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="surface-card overflow-hidden mb-6">
        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
          <h3 className="font-display text-lg font-semibold">
            Order-wise scoring events
          </h3>
          <span className="text-xs text-muted-foreground">
            {events.length} events
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[900px]">
            <thead className="bg-muted/30 text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left font-medium px-6 py-3">Order</th>
                <th className="text-left font-medium py-3">Agent</th>
                <th className="text-left font-medium py-3">Type</th>
                <th className="text-right font-medium py-3">Reward</th>
                <th className="text-right font-medium py-3">Penalty</th>
                <th className="text-right font-medium py-3">Net</th>
                <th className="text-left font-medium py-3">Components</th>
                <th className="text-left font-medium py-3">Missing</th>
                <th className="text-right font-medium px-6 py-3">Calculated</th>
              </tr>
            </thead>
            <tbody>
              {events.length === 0 && (
                <tr>
                  <td
                    colSpan={9}
                    className="px-6 py-6 text-center text-muted-foreground text-sm"
                  >
                    No scoring events yet — run a sweep to populate.
                  </td>
                </tr>
              )}
              {events.map((event) => (
                <tr
                  key={event.id || event.uniqueKey}
                  className="border-t border-border/60 hover:bg-muted/20"
                >
                  <td className="px-6 py-3 font-medium tabular-nums">
                    {event.orderIdSnapshot}
                  </td>
                  <td className="py-3">{event.agentName}</td>
                  <td className="py-3">
                    <StatusPill
                      tone={
                        event.eventType === "reward"
                          ? "success"
                          : event.eventType === "penalty"
                          ? "danger"
                          : "info"
                      }
                    >
                      {event.eventType}
                    </StatusPill>
                  </td>
                  <td className="py-3 text-right text-success font-semibold tabular-nums">
                    +{event.rewardScore}
                  </td>
                  <td className="py-3 text-right text-destructive font-semibold tabular-nums">
                    −{event.penaltyScore}
                  </td>
                  <td className="py-3 text-right font-semibold tabular-nums">
                    {event.netScore}
                  </td>
                  <td className="py-3 text-xs text-muted-foreground max-w-[260px]">
                    {event.components
                      .map((c) => `${c.label} (${c.points >= 0 ? "+" : ""}${c.points})`)
                      .join(", ") || "—"}
                  </td>
                  <td className="py-3 text-xs text-muted-foreground max-w-[160px]">
                    {event.missingData.length > 0 ? event.missingData.join(", ") : "—"}
                  </td>
                  <td className="px-6 py-3 text-right text-xs text-muted-foreground">
                    {formatTimestamp(event.calculatedAt)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {missingWarnings.length > 0 && (
        <div className="surface-card p-5 border-l-4 border-l-amber-500/70">
          <h4 className="font-medium mb-2">Missing data warnings</h4>
          <p className="text-xs text-muted-foreground mb-2">
            The engine never invents missing signals. These orders were scored
            with partial data — fill the gaps to see complete attribution.
          </p>
          <div className="flex flex-wrap gap-1.5">
            {missingWarnings.slice(0, 24).map((w) => (
              <StatusPill key={w} tone="warning">
                {w}
              </StatusPill>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
