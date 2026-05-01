import { useEffect, useRef, useState } from "react";
import {
  Activity, AlertTriangle, Bot, CheckCircle2, CreditCard, IndianRupee, PackageCheck,
  Phone, ShieldAlert, Sparkles, Truck, UserPlus, Users, Workflow, ArrowRight,
} from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { MetricCard } from "@/components/MetricCard";
import { StatusPill } from "@/components/StatusPill";
import { WorkflowMap } from "@/components/WorkflowMap";
import { SaasCoverageCard } from "@/components/SaasCoverageCard";
import { OrgScopeReadinessCard } from "@/components/OrgScopeReadinessCard";
import { Button } from "@/components/ui/button";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend,
  Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api } from "@/services/api";
import { connectAuditEvents } from "@/services/realtime";
import type { ActivityEvent, Agent, CaioAudit, CeoBriefing, RealtimeStatus } from "@/types/domain";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";

const REALTIME_LABEL: Record<RealtimeStatus, string> = {
  connecting: "connecting",
  live: "realtime",
  reconnecting: "reconnecting",
  offline: "polling fallback",
};
const REALTIME_TONE: Record<RealtimeStatus, string> = {
  connecting: "text-muted-foreground",
  live: "text-success",
  reconnecting: "text-warning",
  offline: "text-muted-foreground",
};

function mergeActivityFeed(
  existing: ActivityEvent[],
  incoming: ActivityEvent,
  max: number = 25,
): ActivityEvent[] {
  if (incoming.id !== undefined) {
    if (existing.some((e) => e.id !== undefined && e.id === incoming.id)) {
      return existing;
    }
  }
  return [incoming, ...existing].slice(0, max);
}

const ICONS: Record<string, any> = {
  Phone, Truck, ShieldAlert, CreditCard, Sparkles, AlertTriangle, CheckCircle2, UserPlus,
};

const ACTIVITY_TONES: Record<string, string> = {
  success: "text-success bg-success/10",
  info: "text-info bg-info/10",
  warning: "text-warning bg-warning/10",
  danger: "text-destructive bg-destructive/10",
};

const DASHBOARD_WORKFLOWS = [
  {
    title: "Lead to order workflow",
    description: "Meta or inbound intent becomes a compliant order only after discovery, approved pitch, discount policy and advance-payment attempt.",
    activeIndex: 5,
    steps: ["Meta Lead / Inbound Call", "Lead Captured", "AI Calling", "Problem Discovery", "Product Explanation", "Price / Discount", "Advance Payment", "Order Punched"],
  },
  {
    title: "Delivery and RTO rescue workflow",
    description: "Confirmed orders move through Delhivery tracking, reminder calls and rescue when delivery risk rises.",
    activeIndex: 5,
    steps: ["Confirmed", "AWB Generated", "Pickup Scheduled", "In Transit", "Out for Delivery", "Delivery Reminder", "Delivered / RTO Rescue"],
  },
  {
    title: "CEO AI and CAIO monitoring loop",
    description: "CAIO audits and improves. CEO AI owns approval flow before execution changes affect live business.",
    activeIndex: 3,
    steps: ["Live Data", "Agent Review", "Reward / Penalty", "Learning Gap", "Playbook Improvement", "Approved Update", "Better Performance"],
  },
];

export default function Index() {
  const [m, setM] = useState<any>(null);
  const [funnel, setFunnel] = useState<any[]>([]);
  const [revenue, setRevenue] = useState<any[]>([]);
  const [stateRto, setStateRto] = useState<any[]>([]);
  const [products, setProducts] = useState<any[]>([]);
  const [activity, setActivity] = useState<ActivityEvent[]>([]);
  const [ceo, setCeo] = useState<CeoBriefing | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [audits, setAudits] = useState<CaioAudit[]>([]);
  const [realtimeStatus, setRealtimeStatus] = useState<RealtimeStatus>("connecting");
  const activityRef = useRef<ActivityEvent[]>([]);
  activityRef.current = activity;

  useEffect(() => {
    Promise.all([
      api.getDashboardMetrics(), api.getFunnel(), api.getRevenueTrend(),
      api.getStateRto(), api.getProductPerformance(), api.getLiveActivityFeed(),
      api.getCeoBriefing(), api.getAgentStatus(), api.getCaioAudits(),
    ]).then(([mm, f, r, s, p, a, c, ag, au]) => {
      setM(mm); setFunnel(f); setRevenue(r); setStateRto(s); setProducts(p); setActivity(a);
      setCeo(c); setAgents(ag); setAudits(au);
    });
  }, []);

  // Phase 4A — open the audit-events WebSocket. Snapshot replaces the
  // initial feed; new events prepend with id-deduplication. Existing
  // polling endpoints keep working as fallback when the socket is offline.
  useEffect(() => {
    const ctrl = connectAuditEvents({
      onSnapshot: (events) => {
        if (events.length > 0) setActivity(events.slice(0, 25));
      },
      onEvent: (event) => {
        setActivity((prev) => mergeActivityFeed(prev, event, 25));
      },
      onStatusChange: setRealtimeStatus,
    });
    return () => ctrl.close();
  }, []);

  if (!m || !ceo) return <div className="h-96 grid place-items-center text-muted-foreground">Loading command center...</div>;

  return (
    <>
      <PageHeader
        eyebrow="Command Center"
        title="Good morning, Prarit."
        description="Here is the full picture of Nirogidhara — leads, calls, orders, delivery and AI governance — in one glance."
        actions={
          <>
            <Button variant="outline" asChild><Link to="/agents">View AI Agents</Link></Button>
            <Button className="bg-gradient-hero text-primary-foreground hover:opacity-95" asChild>
              <Link to="/ceo-ai"><Sparkles className="h-4 w-4 mr-1.5" />CEO AI Briefing</Link>
            </Button>
          </>
        }
      />

      {/* CEO AI hero strip */}
      <div className="surface-elevated overflow-hidden mb-8 relative noise-overlay">
        <div className="absolute inset-0 bg-gradient-hero" />
        <div className="absolute -right-24 -top-24 h-80 w-80 rounded-full bg-accent/35 blur-3xl" />
        <div className="absolute right-1/3 -bottom-28 h-72 w-72 rounded-full bg-primary-glow/40 blur-3xl" />
        <div className="absolute inset-0 opacity-[0.07]" style={{
          backgroundImage: "linear-gradient(hsl(0 0% 100% / 0.5) 1px, transparent 1px), linear-gradient(90deg, hsl(0 0% 100% / 0.5) 1px, transparent 1px)",
          backgroundSize: "40px 40px",
        }} />
        <div className="relative p-6 lg:p-9 grid lg:grid-cols-[1fr_auto] gap-6 items-center text-primary-foreground">
          <div>
            <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full bg-white/10 ring-1 ring-white/15 backdrop-blur-sm text-[10.5px] uppercase tracking-[0.22em] font-semibold text-accent mb-4">
              <Sparkles className="h-3 w-3" /> CEO AI · {ceo.date}
            </div>
            <h2 className="font-display text-[26px] lg:text-[34px] font-semibold text-balance leading-[1.12]">
              {ceo.headline}
            </h2>
            <p className="mt-3 text-primary-foreground/75 text-[14.5px] max-w-2xl leading-relaxed text-pretty">
              {ceo.summary}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" className="bg-white/10 hover:bg-white/15 border border-white/15 text-primary-foreground backdrop-blur-sm" asChild>
              <Link to="/ceo-ai">Review {ceo.recommendations.length} actions <ArrowRight className="h-4 w-4 ml-1" /></Link>
            </Button>
            <Button className="bg-gradient-gold text-accent-foreground hover:opacity-95 border-0 shadow-glow" asChild>
              <Link to="/caio">CAIO Audit</Link>
            </Button>
          </div>
        </div>
      </div>

      {/* Hero KPIs — most important */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 mb-4 animate-rise-stagger">
        <MetricCard emphasis icon={IndianRupee} label="Net Delivered Profit · 7d" value={`₹${(m.netProfit.value/1000).toFixed(0)}K`} delta={m.netProfit.deltaPct} tone="success" sublabel="after ad, RTO & gateway costs" />
        <MetricCard emphasis icon={PackageCheck} label="Delivered Today" value={m.delivered.value} delta={m.delivered.deltaPct} tone="primary" sublabel="signed & accepted" />
        <MetricCard emphasis icon={ShieldAlert} label="RTO Risk Queue" value={m.rtoRisk.value} delta={m.rtoRisk.deltaPct} tone="warning" sublabel="awaiting rescue call" />
        <MetricCard emphasis icon={Sparkles} label="CEO AI Approvals" value={m.ceoAlerts.value} tone="accent" sublabel="awaiting your nod" />
      </div>

      {/* Phase 6B + 6C — read-only SaaS coverage + org-scope readiness. */}
      <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4 mb-4">
        <SaasCoverageCard />
        <OrgScopeReadinessCard />
      </div>

      {/* Section divider */}
      <div className="flex items-center gap-3 mb-4 mt-6">
        <div className="text-[10.5px] uppercase tracking-[0.22em] text-muted-foreground font-semibold">Operational pulse</div>
        <div className="flex-1 divider-soft" />
      </div>

      {/* Supporting KPI grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-8 gap-3 mb-8 animate-rise-stagger">
        <MetricCard icon={Users} label="Leads" value={m.leadsToday.value.toLocaleString()} delta={m.leadsToday.deltaPct} tone="info" sublabel="today" />
        <MetricCard icon={Phone} label="Calls Live · Done" value={`${m.callsRunning.value} · ${m.callsRunning.completed}`} tone="accent" />
        <MetricCard icon={Workflow} label="Orders Punched" value={m.ordersPunched.value} delta={m.ordersPunched.deltaPct} tone="primary" />
        <MetricCard icon={CheckCircle2} label="Confirmed" value={m.ordersConfirmed.value} delta={m.ordersConfirmed.deltaPct} tone="success" />
        <MetricCard icon={Truck} label="In Transit" value={m.inTransit.value} delta={m.inTransit.deltaPct} tone="info" />
        <MetricCard icon={CreditCard} label="Paid · Pending" value={`${m.paymentsPaid.value}·${m.paymentsPaid.pending}`} tone="accent" />
        <MetricCard icon={Bot} label="Agents Health" value={`${m.agentHealth.value}%`} tone="primary" sublabel={`${m.agentHealth.alerts} alerts`} />
        <MetricCard icon={AlertTriangle} label="CAIO Flags" value={m.caioAlerts.value} tone="danger" />
      </div>

      {/* Funnel + Revenue */}
      <div className="grid xl:grid-cols-3 gap-6 mb-8">
        <div className="surface-card p-6 xl:col-span-2">
          <div className="flex items-center justify-between mb-1">
            <h3 className="font-display text-xl font-semibold">Lead → Delivery Funnel</h3>
            <StatusPill tone="info">Last 7 days</StatusPill>
          </div>
          <p className="text-sm text-muted-foreground mb-5">Volume drop at each stage. Tap on Analytics for cohort breakdowns.</p>
          <div className="space-y-3">
            {funnel.map((s, i) => {
              const max = funnel[0].value;
              const pct = (s.value / max) * 100;
              const conversion = i === 0 ? 100 : (s.value / funnel[0].value) * 100;
              return (
                <div key={s.stage}>
                  <div className="flex items-baseline justify-between mb-1">
                    <span className="text-sm font-medium">{s.stage}</span>
                    <span className="text-sm tabular-nums">
                      <span className="font-semibold">{s.value.toLocaleString()}</span>
                      <span className="text-muted-foreground ml-2 text-xs">{conversion.toFixed(1)}%</span>
                    </span>
                  </div>
                  <div className="h-3 rounded-full bg-muted overflow-hidden">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-primary to-primary-glow transition-all duration-700"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="surface-card p-6">
          <div className="flex items-center justify-between mb-1">
            <h3 className="font-display text-xl font-semibold">Revenue & Profit</h3>
            <StatusPill tone="success">+18.4%</StatusPill>
          </div>
          <p className="text-sm text-muted-foreground mb-3">Net delivered (₹ in K)</p>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={revenue}>
              <defs>
                <linearGradient id="gRev" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="gPro" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="hsl(var(--accent))" stopOpacity={0.5} />
                  <stop offset="100%" stopColor="hsl(var(--accent))" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
              <XAxis dataKey="d" stroke="hsl(var(--muted-foreground))" fontSize={11} />
              <YAxis stroke="hsl(var(--muted-foreground))" fontSize={11} />
              <Tooltip contentStyle={{ borderRadius: 12, border: '1px solid hsl(var(--border))', fontSize: 12, background: 'hsl(var(--card))' }} />
              <Area type="monotone" dataKey="revenue" stroke="hsl(var(--primary))" strokeWidth={2} fill="url(#gRev)" />
              <Area type="monotone" dataKey="profit" stroke="hsl(var(--accent))" strokeWidth={2} fill="url(#gPro)" />
            </AreaChart>
          </ResponsiveContainer>
          <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-primary" />Revenue</span>
            <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-accent" />Profit</span>
          </div>
        </div>
      </div>

      {/* Agents row + activity */}
      <div className="grid xl:grid-cols-3 gap-6 mb-8">
        <div className="surface-card p-6 xl:col-span-2">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="font-display text-xl font-semibold">AI Agent Health</h3>
              <p className="text-sm text-muted-foreground">Live status of the six core agents</p>
            </div>
            <Button variant="ghost" size="sm" asChild><Link to="/agents">All agents <ArrowRight className="h-3 w-3 ml-1" /></Link></Button>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {agents.filter((a) => ["ceo", "caio", "calling-tl", "rto", "compliance", "cfo"].includes(a.id)).map((a) => (
              <div key={a.id} className="rounded-xl border border-border/60 bg-gradient-emerald-soft/40 p-4 hover:shadow-soft transition">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-semibold text-foreground">{a.name}</div>
                  <StatusPill tone={a.status === "active" ? "success" : a.status === "warning" ? "warning" : "danger"}>{a.status}</StatusPill>
                </div>
                <div className="text-[11px] text-muted-foreground mt-0.5 truncate">{a.role}</div>
                <div className="mt-3 flex items-baseline justify-between">
                  <div className="font-display text-2xl font-semibold">{a.health}%</div>
                  <div className="text-[11px] text-muted-foreground">health</div>
                </div>
                <div className="h-1.5 rounded-full bg-background mt-1 overflow-hidden">
                  <div className={cn("h-full rounded-full", a.health > 90 ? "bg-success" : a.health > 80 ? "bg-info" : "bg-warning")} style={{ width: `${a.health}%` }} />
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="surface-card p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-display text-xl font-semibold">Live Activity</h3>
            <span
              className={cn(
                "inline-flex items-center gap-1.5 text-xs capitalize",
                REALTIME_TONE[realtimeStatus],
              )}
            >
              {realtimeStatus === "live" && <span className="live-dot" />}
              {REALTIME_LABEL[realtimeStatus]}
            </span>
          </div>
          <ul className="space-y-3 max-h-[420px] overflow-auto scrollbar-thin pr-2">
            {activity.map((a, i) => {
              const Icon = ICONS[a.icon] || Activity;
              return (
                <li key={a.id ?? i} className="flex gap-3 animate-rise">
                  <div className={cn("h-8 w-8 rounded-lg grid place-items-center shrink-0", ACTIVITY_TONES[a.tone])}>
                    <Icon className="h-4 w-4" />
                  </div>
                  <div className="text-sm leading-snug">
                    <div className="text-foreground">{a.text}</div>
                    <div className="text-[11px] text-muted-foreground mt-0.5">{a.time}</div>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      </div>

      {/* Region RTO + Product perf + Reward summary */}
      <div className="grid xl:grid-cols-3 gap-6 mb-8">
        <div className="surface-card p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="font-display text-xl font-semibold">RTO by Region</h3>
              <p className="text-sm text-muted-foreground">% returned in last 30 days</p>
            </div>
            <StatusPill tone="warning">High in 3 states</StatusPill>
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={stateRto} layout="vertical" margin={{ left: 4, right: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" horizontal={false} />
              <XAxis type="number" stroke="hsl(var(--muted-foreground))" fontSize={11} />
              <YAxis type="category" dataKey="state" stroke="hsl(var(--muted-foreground))" fontSize={11} width={88} />
              <Tooltip contentStyle={{ borderRadius: 12, border: '1px solid hsl(var(--border))', fontSize: 12 }} />
              <Bar dataKey="rto" radius={[0, 8, 8, 0]}>
                {stateRto.map((s, i) => (
                  <Cell key={i} fill={s.rto > 25 ? "hsl(var(--destructive))" : s.rto > 15 ? "hsl(var(--warning))" : "hsl(var(--success))"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="surface-card p-6 xl:col-span-2">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="font-display text-xl font-semibold">Product Performance</h3>
              <p className="text-sm text-muted-foreground">Net delivered profit by category</p>
            </div>
            <Button variant="ghost" size="sm" asChild><Link to="/analytics">Full report <ArrowRight className="h-3 w-3 ml-1" /></Link></Button>
          </div>
          <div className="overflow-x-auto -mx-6">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[11px] uppercase tracking-wider text-muted-foreground border-b border-border">
                  <th className="text-left font-medium px-6 py-2">Product</th>
                  <th className="text-right font-medium py-2">Leads</th>
                  <th className="text-right font-medium py-2">Orders</th>
                  <th className="text-right font-medium py-2">Delivered</th>
                  <th className="text-right font-medium py-2">RTO%</th>
                  <th className="text-right font-medium px-6 py-2">Net Profit</th>
                </tr>
              </thead>
              <tbody>
                {products.map((p) => (
                  <tr key={p.product} className="border-b border-border/60 hover:bg-muted/40">
                    <td className="px-6 py-3 font-medium">{p.product}</td>
                    <td className="text-right tabular-nums">{p.leads}</td>
                    <td className="text-right tabular-nums">{p.orders}</td>
                    <td className="text-right tabular-nums">{p.delivered}</td>
                    <td className="text-right">
                      <StatusPill tone={p.rtoPct > 18 ? "danger" : p.rtoPct > 12 ? "warning" : "success"}>{p.rtoPct}%</StatusPill>
                    </td>
                    <td className="px-6 py-3 text-right font-semibold tabular-nums">₹{(p.netProfit/1000).toFixed(1)}K</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="grid xl:grid-cols-3 gap-6 mb-8">
        {DASHBOARD_WORKFLOWS.map((workflow) => (
          <WorkflowMap key={workflow.title} {...workflow} compact />
        ))}
      </div>

      {/* CAIO + Reward */}
      <div className="grid lg:grid-cols-2 gap-6">
        <div className="surface-card p-6 border-l-4 border-l-warning">
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle className="h-4 w-4 text-warning" />
            <h3 className="font-display text-xl font-semibold">CAIO Critical Audit</h3>
          </div>
          <p className="text-sm text-muted-foreground mb-4">Governance & training observations — never executes business actions.</p>
          <ul className="space-y-3">
            {audits.slice(0, 3).map((a, i) => (
              <li key={i} className="flex gap-3">
                <StatusPill tone={a.severity === "Critical" ? "danger" : a.severity === "High" ? "warning" : "info"}>{a.severity}</StatusPill>
                <div className="text-sm">
                  <div className="font-medium">{a.agent}</div>
                  <div className="text-muted-foreground">{a.issue}</div>
                </div>
              </li>
            ))}
          </ul>
          <Button variant="ghost" size="sm" className="mt-4" asChild><Link to="/caio">Open CAIO Center <ArrowRight className="h-3 w-3 ml-1" /></Link></Button>
        </div>

        <div className="surface-card p-6 border-l-4 border-l-accent">
          <div className="flex items-center gap-2 mb-2">
            <Sparkles className="h-4 w-4 text-accent" />
            <h3 className="font-display text-xl font-semibold">Reward / Penalty Summary</h3>
          </div>
          <p className="text-sm text-muted-foreground mb-4">CEO AI distributes points based on root-cause attribution.</p>
          <div className="grid grid-cols-3 gap-3 mb-4">
            <div className="rounded-xl bg-success/10 p-3">
              <div className="text-[11px] text-success font-medium">Reward</div>
              <div className="font-display text-2xl font-semibold text-success">+5,210</div>
            </div>
            <div className="rounded-xl bg-destructive/10 p-3">
              <div className="text-[11px] text-destructive font-medium">Penalty</div>
              <div className="font-display text-2xl font-semibold text-destructive">−486</div>
            </div>
            <div className="rounded-xl bg-gradient-gold/10 p-3 border border-accent/20">
              <div className="text-[11px] text-accent-foreground/80 font-medium">Net</div>
              <div className="font-display text-2xl font-semibold">4,724</div>
            </div>
          </div>
          <Button variant="ghost" size="sm" asChild><Link to="/rewards">Open leaderboard <ArrowRight className="h-3 w-3 ml-1" /></Link></Button>
        </div>
      </div>
    </>
  );
}
