import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import * as M from "@/services/mockData";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Award, Minus, Plus, Trophy } from "lucide-react";

const REWARDS = ["Delivered order", "Net delivered profit", "Advance payment", "Customer satisfaction", "Reorder potential", "Compliance safety"];
const PENALTIES = ["Bad lead quality", "Weak closing", "Wrong address", "Missed delivery reminder", "Risky claim", "RTO risk ignored", "Over-discount"];

export default function Rewards() {
  return (
    <>
      <PageHeader eyebrow="Governance" title="Reward & Penalty Engine"
        description="CEO AI distributes points to contributing agents based on root-cause analysis."
      />

      <div className="grid sm:grid-cols-3 gap-4 mb-6">
        <div className="surface-card p-5 border-l-4 border-l-success">
          <div className="flex items-center gap-2 text-success"><Plus className="h-4 w-4" /><span className="text-xs uppercase tracking-wider font-semibold">Reward total</span></div>
          <div className="font-display text-3xl font-semibold mt-1">+5,210</div>
        </div>
        <div className="surface-card p-5 border-l-4 border-l-destructive">
          <div className="flex items-center gap-2 text-destructive"><Minus className="h-4 w-4" /><span className="text-xs uppercase tracking-wider font-semibold">Penalty total</span></div>
          <div className="font-display text-3xl font-semibold mt-1">−486</div>
        </div>
        <div className="surface-card p-5 border-l-4 border-l-accent">
          <div className="flex items-center gap-2 text-accent-foreground"><Trophy className="h-4 w-4 text-accent" /><span className="text-xs uppercase tracking-wider font-semibold">Net AI score</span></div>
          <div className="font-display text-3xl font-semibold mt-1 gold-text">4,724</div>
        </div>
      </div>

      <div className="surface-card p-6 mb-6 bg-gradient-emerald-soft">
        <h3 className="font-display text-lg font-semibold mb-2 flex items-center gap-2"><Award className="h-5 w-5 text-accent" />Net Delivered Profit formula</h3>
        <code className="block text-sm bg-background/70 rounded-lg p-3 font-mono">
          Delivered Revenue − Ad Cost − Discount − Courier Cost − RTO Loss − Payment Gateway Charges − Product Cost
        </code>
      </div>

      <div className="grid xl:grid-cols-[1.4fr_1fr] gap-6 mb-6">
        <div className="surface-card p-6">
          <h3 className="font-display text-lg font-semibold mb-3">Agent leaderboard</h3>
          <ResponsiveContainer width="100%" height={340}>
            <BarChart data={M.REWARD_LEADERBOARD.slice(0, 8)} layout="vertical" margin={{ left: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" horizontal={false} />
              <XAxis type="number" stroke="hsl(var(--muted-foreground))" fontSize={11} />
              <YAxis type="category" dataKey="name" stroke="hsl(var(--muted-foreground))" fontSize={11} width={170} />
              <Tooltip contentStyle={{ borderRadius: 12, border: '1px solid hsl(var(--border))', fontSize: 12 }} />
              <Bar dataKey="reward" stackId="a" fill="hsl(var(--success))" />
              <Bar dataKey="penalty" stackId="a" fill="hsl(var(--destructive))" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="space-y-4">
          <div className="surface-card p-5">
            <h4 className="font-medium mb-2 text-success">Reward triggers</h4>
            <div className="flex flex-wrap gap-1.5">{REWARDS.map((r) => <StatusPill key={r} tone="success">{r}</StatusPill>)}</div>
          </div>
          <div className="surface-card p-5">
            <h4 className="font-medium mb-2 text-destructive">Penalty triggers</h4>
            <div className="flex flex-wrap gap-1.5">{PENALTIES.map((p) => <StatusPill key={p} tone="danger">{p}</StatusPill>)}</div>
          </div>
        </div>
      </div>

      <div className="surface-card overflow-hidden">
        <div className="px-6 py-4 border-b border-border"><h3 className="font-display text-lg font-semibold">Root-cause attribution</h3></div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[700px]">
            <thead className="bg-muted/30 text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left font-medium px-6 py-3">Agent</th>
                <th className="text-right font-medium py-3">Reward</th>
                <th className="text-right font-medium py-3">Penalty</th>
                <th className="text-right font-medium px-6 py-3">Net</th>
              </tr>
            </thead>
            <tbody>
              {M.REWARD_LEADERBOARD.map((r) => (
                <tr key={r.name} className="border-t border-border/60 hover:bg-muted/20">
                  <td className="px-6 py-3 font-medium">{r.name}</td>
                  <td className="py-3 text-right text-success font-semibold tabular-nums">+{r.reward}</td>
                  <td className="py-3 text-right text-destructive font-semibold tabular-nums">−{r.penalty}</td>
                  <td className="px-6 py-3 text-right font-semibold tabular-nums">{r.net}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}