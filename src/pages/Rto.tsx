import { useEffect, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill, toneForStatus } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { api } from "@/services/api";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlertTriangle, ShieldCheck, PhoneCall, MapPin } from "lucide-react";
import { toast } from "sonner";

export default function Rto() {
  const [orders, setOrders] = useState<any[]>([]);
  const [stateRto, setStateRto] = useState<any[]>([]);

  useEffect(() => {
    api.getRtoRiskOrders().then(setOrders);
    api.getStateRto().then(setStateRto);
  }, []);

  return (
    <>
      <PageHeader eyebrow="Operations" title="RTO Rescue Board"
        description="Predict, rescue and root-cause Return-to-Origin orders before they ship back."
      />

      <div className="surface-elevated p-6 mb-6 bg-gradient-leaf">
        <h3 className="font-display text-lg font-semibold mb-3">Rescue workflow</h3>
        <div className="flex flex-wrap items-center gap-2">
          {["Risk Detected", "RTO Agent Rescue Call", "Customer Convinced?", "Yes → Continue", "No → Return to Warehouse"].map((s, i, arr) => (
            <div key={s} className="flex items-center gap-2">
              <span className={`px-3 py-1.5 rounded-full text-xs font-medium ${i === 0 ? "bg-warning text-warning-foreground" : i === 3 ? "bg-success text-success-foreground" : i === 4 ? "bg-destructive text-destructive-foreground" : "bg-muted text-foreground"}`}>{s}</span>
              {i < arr.length - 1 && <span className="text-muted-foreground">→</span>}
            </div>
          ))}
        </div>
      </div>

      <div className="grid xl:grid-cols-[1.4fr_1fr] gap-6 mb-6">
        <div className="surface-card p-6">
          <div className="flex items-center justify-between mb-2">
            <h3 className="font-display text-xl font-semibold">High-risk orders</h3>
            <StatusPill tone="warning">{orders.length} active</StatusPill>
          </div>
          <div className="space-y-3 max-h-[520px] overflow-auto scrollbar-thin">
            {orders.map((o) => (
              <div key={o.id} className="rounded-xl border border-border bg-card p-4">
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <div className="font-medium">{o.customerName} <span className="text-xs text-muted-foreground font-mono">· {o.id}</span></div>
                    <div className="text-xs text-muted-foreground"><MapPin className="h-3 w-3 inline mr-0.5" />{o.city}, {o.state} · {o.product}</div>
                  </div>
                  <div className="text-right">
                    <div className="font-display text-2xl font-semibold text-destructive">{o.rtoScore}</div>
                    <div className="text-[10px] text-muted-foreground uppercase tracking-wider">RTO score</div>
                  </div>
                </div>
                <div className="flex flex-wrap gap-1.5 mb-2">
                  {o.riskReasons.map((r: string) => <StatusPill key={r} tone="warning" icon={<AlertTriangle className="h-3 w-3" />}>{r}</StatusPill>)}
                </div>
                <div className="flex items-center justify-between mt-3">
                  <StatusPill tone={toneForStatus(o.rescueStatus)}>{o.rescueStatus}</StatusPill>
                  <div className="flex gap-2">
                    <Button size="sm" variant="outline" onClick={() => toast.success(`Rescue call queued for ${o.id}`)}><PhoneCall className="h-3.5 w-3.5 mr-1" />Rescue</Button>
                    <Button size="sm" className="bg-gradient-hero text-primary-foreground" onClick={() => toast.success(`${o.id} marked convinced`)}><ShieldCheck className="h-3.5 w-3.5 mr-1" />Convinced</Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="space-y-6">
          <div className="surface-card p-6">
            <h3 className="font-display text-lg font-semibold mb-3">Top RTO regions</h3>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={stateRto} layout="vertical" margin={{ left: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" horizontal={false} />
                <XAxis type="number" stroke="hsl(var(--muted-foreground))" fontSize={11} />
                <YAxis type="category" dataKey="state" stroke="hsl(var(--muted-foreground))" fontSize={11} width={90} />
                <Tooltip contentStyle={{ borderRadius: 12, border: '1px solid hsl(var(--border))', fontSize: 12 }} />
                <Bar dataKey="rto" radius={[0, 8, 8, 0]}>
                  {stateRto.map((s, i) => <Cell key={i} fill={s.rto > 25 ? "hsl(var(--destructive))" : s.rto > 15 ? "hsl(var(--warning))" : "hsl(var(--success))"} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="surface-card p-6 border-l-4 border-l-accent">
            <h3 className="font-display text-lg font-semibold mb-2">RTO Agent suggestions</h3>
            <ul className="space-y-2 text-sm">
              <li className="flex gap-2"><span className="text-accent">•</span>Mandatory ₹499 advance for Rajasthan COD pin codes.</li>
              <li className="flex gap-2"><span className="text-accent">•</span>Add 2nd reminder call 6h before delivery in Bihar & UP.</li>
              <li className="flex gap-2"><span className="text-accent">•</span>Block discounts {">"}25% on first-time COD customers.</li>
            </ul>
          </div>
        </div>
      </div>
    </>
  );
}