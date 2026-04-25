import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Calendar, Filter } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/services/api";
import { useEffect, useState } from "react";

export default function Analytics() {
  const [data, setData] = useState<any>(null);

  useEffect(() => { api.getAnalyticsData().then(setData); }, []);

  if (!data) return <div className="h-96 grid place-items-center text-muted-foreground">Loading analytics...</div>;

  return (
    <>
      <PageHeader eyebrow="Insights" title="Analytics"
        description="Funnel, products, regions, RTO, discount impact, agent performance and net delivered profit."
        actions={
          <>
            <Button variant="outline"><Calendar className="h-4 w-4 mr-1.5" />Last 30 days</Button>
            <Button variant="outline"><Filter className="h-4 w-4 mr-1.5" />Filters</Button>
          </>
        }
      />

      <div className="grid xl:grid-cols-2 gap-6 mb-6">
        <div className="surface-card p-6">
          <h3 className="font-display text-lg font-semibold mb-3">Revenue & Profit (₹K)</h3>
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={data.revenueTrend}>
              <defs>
                <linearGradient id="r" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity={0.4} />
                  <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="d" fontSize={11} stroke="hsl(var(--muted-foreground))" />
              <YAxis fontSize={11} stroke="hsl(var(--muted-foreground))" />
              <Tooltip contentStyle={{ borderRadius: 12, border: '1px solid hsl(var(--border))', fontSize: 12 }} />
              <Area type="monotone" dataKey="revenue" stroke="hsl(var(--primary))" strokeWidth={2} fill="url(#r)" />
              <Area type="monotone" dataKey="profit" stroke="hsl(var(--accent))" strokeWidth={2} fill="hsl(var(--accent) / 0.1)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="surface-card p-6">
          <h3 className="font-display text-lg font-semibold mb-3">Funnel volumes</h3>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={data.funnel}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="stage" fontSize={10} stroke="hsl(var(--muted-foreground))" interval={0} angle={-15} textAnchor="end" height={60} />
              <YAxis fontSize={11} stroke="hsl(var(--muted-foreground))" />
              <Tooltip contentStyle={{ borderRadius: 12, border: '1px solid hsl(var(--border))', fontSize: 12 }} />
              <Bar dataKey="value" radius={[6, 6, 0, 0]} fill="hsl(var(--primary))" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="surface-card p-6">
          <h3 className="font-display text-lg font-semibold mb-3">RTO % by state</h3>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={data.stateRto}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="state" fontSize={11} stroke="hsl(var(--muted-foreground))" />
              <YAxis fontSize={11} stroke="hsl(var(--muted-foreground))" />
              <Tooltip contentStyle={{ borderRadius: 12, border: '1px solid hsl(var(--border))', fontSize: 12 }} />
              <Bar dataKey="rto" radius={[6, 6, 0, 0]}>
                {data.stateRto.map((s: any, i: number) => <Cell key={i} fill={s.rto > 25 ? "hsl(var(--destructive))" : s.rto > 15 ? "hsl(var(--warning))" : "hsl(var(--success))"} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="surface-card p-6">
          <h3 className="font-display text-lg font-semibold mb-3">Discount impact on delivered orders</h3>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={data.discountImpact}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="discount" fontSize={11} stroke="hsl(var(--muted-foreground))" />
              <YAxis fontSize={11} stroke="hsl(var(--muted-foreground))" />
              <Tooltip contentStyle={{ borderRadius: 12, border: '1px solid hsl(var(--border))', fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line type="monotone" dataKey="delivered" stroke="hsl(var(--success))" strokeWidth={2.5} dot={{ r: 4 }} />
              <Line type="monotone" dataKey="rto" stroke="hsl(var(--destructive))" strokeWidth={2.5} dot={{ r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="surface-card overflow-hidden">
        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
          <h3 className="font-display text-lg font-semibold">Product performance</h3>
          <StatusPill tone="info">Last 30 days</StatusPill>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[800px]">
            <thead className="bg-muted/30 text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left font-medium px-6 py-3">Product</th>
                <th className="text-right font-medium py-3">Leads</th>
                <th className="text-right font-medium py-3">Orders</th>
                <th className="text-right font-medium py-3">Delivered</th>
                <th className="text-right font-medium py-3">RTO%</th>
                <th className="text-right font-medium px-6 py-3">Net Profit</th>
              </tr>
            </thead>
            <tbody>
              {data.productPerformance.map((p: any) => (
                <tr key={p.product} className="border-t border-border/60 hover:bg-muted/20">
                  <td className="px-6 py-3 font-medium">{p.product}</td>
                  <td className="py-3 text-right tabular-nums">{p.leads}</td>
                  <td className="py-3 text-right tabular-nums">{p.orders}</td>
                  <td className="py-3 text-right tabular-nums">{p.delivered}</td>
                  <td className="py-3 text-right"><StatusPill tone={p.rtoPct > 18 ? "danger" : p.rtoPct > 12 ? "warning" : "success"}>{p.rtoPct}%</StatusPill></td>
                  <td className="px-6 py-3 text-right font-semibold tabular-nums">₹{(p.netProfit/1000).toFixed(1)}K</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
