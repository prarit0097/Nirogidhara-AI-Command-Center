import { useEffect, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill, toneForStatus } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { api } from "@/services/api";
import type { ActiveCall, Call } from "@/types/domain";
import { Activity, Bot, CheckCircle2, FileBadge2, Phone, PhoneCall, ShieldCheck, UserSquare2, Volume2 } from "lucide-react";

const WORKFLOW = [
  "Lead Assigned", "Language Detected", "Greeting & Consent", "Problem Discovery",
  "Lifestyle Questions", "Approved Product Pitch", "Objection Handling", "Price & Discount",
  "Advance Payment", "Address Capture", "Order Created",
];

export default function Calling() {
  const [calls, setCalls] = useState<Call[]>([]);
  const [live, setLive] = useState<ActiveCall | null>(null);
  useEffect(() => {
    Promise.all([api.getCalls(), api.getActiveCall()]).then(([callRows, activeCall]) => {
      setCalls(callRows);
      setLive(activeCall);
    });
  }, []);

  if (!live) return <div className="h-96 grid place-items-center text-muted-foreground">Loading calling console...</div>;

  return (
    <>
      <PageHeader eyebrow="Sales" title="AI Calling Console"
        description="Live AI calling operations. Every word is grounded in the Approved Claim Vault — no free-style medical claims."
        actions={<Button variant="outline" className="gap-1.5"><UserSquare2 className="h-4 w-4" />Human handoff</Button>}
      />

      <div className="grid xl:grid-cols-3 gap-6 mb-6">
        <Stat icon={Activity} label="Active calls" value="18" tone="success" />
        <Stat icon={Phone} label="Queue" value="42" tone="info" />
        <Stat icon={CheckCircle2} label="Completed today" value="412" tone="primary" />
      </div>

      <div className="grid xl:grid-cols-[1.4fr_1fr] gap-6 mb-6">
        {/* Live call */}
        <div className="surface-elevated p-6 relative overflow-hidden">
          <div className="absolute -right-20 -top-20 h-60 w-60 rounded-full bg-success/15 blur-3xl" />
          <div className="flex items-start justify-between mb-5 relative">
            <div>
              <div className="text-xs uppercase tracking-wider text-success font-semibold flex items-center gap-1.5"><span className="live-dot" />Live</div>
              <div className="font-display text-2xl font-semibold mt-1">{live.customer}</div>
              <div className="text-sm text-muted-foreground">{live.phone} · {live.language} · {live.duration}</div>
            </div>
            <div className="flex flex-col items-end gap-1.5">
              <StatusPill tone="info"><Bot className="h-3 w-3 mr-1" />{live.agent}</StatusPill>
              <StatusPill tone="warning">Sentiment · {live.sentiment}</StatusPill>
              <StatusPill tone="success" icon={<ShieldCheck className="h-3 w-3" />}>Compliance {live.scriptCompliance}%</StatusPill>
            </div>
          </div>

          <div className="rounded-xl border border-border bg-background/60 p-4 max-h-[280px] overflow-auto scrollbar-thin space-y-2">
            {live.transcript.map((t, i) => (
              <div key={i} className={`flex gap-2 ${t.who === "AI" ? "" : "justify-end"}`}>
                <div className={`max-w-[80%] rounded-2xl px-3 py-2 text-sm ${t.who === "AI" ? "bg-gradient-emerald-soft text-foreground rounded-tl-sm" : "bg-foreground text-background rounded-tr-sm"}`}>
                  <div className="text-[10px] opacity-60 mb-0.5">{t.who}</div>
                  {t.text}
                </div>
              </div>
            ))}
          </div>

          <div className="grid sm:grid-cols-2 gap-3 mt-5">
            <div className="rounded-xl bg-muted/50 p-3">
              <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1.5">Detected objections</div>
              <div className="flex flex-wrap gap-1.5">{live.detectedObjections.map((o) => <StatusPill key={o} tone="warning">{o}</StatusPill>)}</div>
            </div>
            <div className="rounded-xl bg-muted/50 p-3">
              <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1.5 flex items-center gap-1.5"><FileBadge2 className="h-3 w-3" />Approved claims used</div>
              <div className="flex flex-wrap gap-1.5">{live.approvedClaimsUsed.map((c) => <StatusPill key={c} tone="success">{c}</StatusPill>)}</div>
            </div>
          </div>

          <div className="flex flex-wrap gap-2 mt-5">
            <Button className="bg-gradient-hero text-primary-foreground"><PhoneCall className="h-4 w-4 mr-1.5" />Create order</Button>
            <Button variant="outline"><UserSquare2 className="h-4 w-4 mr-1.5" />Hand off to human</Button>
            <Button variant="outline"><Volume2 className="h-4 w-4 mr-1.5" />Listen-in</Button>
          </div>
        </div>

        {/* Workflow */}
        <div className="surface-card p-6">
          <h3 className="font-display text-lg font-semibold mb-4">Call workflow</h3>
          <ol className="relative border-l-2 border-border ml-2 space-y-3">
            {WORKFLOW.map((s, i) => {
              const done = i <= 6;
              const current = i === 6;
              return (
                <li key={s} className="ml-4 relative">
                  <span className={`absolute -left-[22px] top-1 h-3 w-3 rounded-full ring-4 ring-background ${done ? "bg-primary" : "bg-muted"} ${current ? "animate-pulse-glow ring-accent/30" : ""}`} />
                  <div className={`text-sm ${current ? "font-semibold text-foreground" : done ? "text-foreground" : "text-muted-foreground"}`}>
                    {s}
                  </div>
                </li>
              );
            })}
          </ol>
          <div className="rounded-xl bg-accent-soft border border-accent/30 p-3 mt-5 text-xs text-foreground">
            <ShieldCheck className="h-4 w-4 text-accent inline mr-1.5" />
            AI uses <strong>Approved Claim Vault</strong> only. No free-style medical claims.
          </div>
        </div>
      </div>

      {/* Calls table */}
      <div className="surface-card overflow-hidden">
        <div className="px-6 py-4 border-b border-border">
          <h3 className="font-display text-lg font-semibold">Recent calls</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[900px]">
            <thead className="bg-muted/30 text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left font-medium px-6 py-3">Customer</th>
                <th className="text-left font-medium py-3">Agent</th>
                <th className="text-left font-medium py-3">Language</th>
                <th className="text-left font-medium py-3">Duration</th>
                <th className="text-left font-medium py-3">Sentiment</th>
                <th className="text-left font-medium py-3">Compliance</th>
                <th className="text-left font-medium py-3">Status</th>
                <th className="text-left font-medium px-6 py-3">Pay link</th>
              </tr>
            </thead>
            <tbody>
              {calls.map((c) => (
                <tr key={c.id} className="border-t border-border/60 hover:bg-muted/20">
                  <td className="px-6 py-3 font-medium">{c.customer}<div className="text-[11px] text-muted-foreground font-mono">{c.phone}</div></td>
                  <td className="py-3">{c.agent}</td>
                  <td className="py-3">{c.language}</td>
                  <td className="py-3 tabular-nums">{c.duration}</td>
                  <td className="py-3"><StatusPill tone={toneForStatus(c.sentiment)}>{c.sentiment}</StatusPill></td>
                  <td className="py-3"><StatusPill tone={c.scriptCompliance > 90 ? "success" : "warning"}>{c.scriptCompliance}%</StatusPill></td>
                  <td className="py-3"><StatusPill tone={toneForStatus(c.status)}>{c.status}</StatusPill></td>
                  <td className="px-6 py-3">{c.paymentLinkSent ? <StatusPill tone="success">Sent</StatusPill> : <span className="text-muted-foreground">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

function Stat({ icon: Icon, label, value, tone }: { icon: any; label: string; value: string; tone: any }) {
  return (
    <div className="surface-card p-5 flex items-center gap-4">
      <div className={`h-12 w-12 rounded-xl grid place-items-center bg-${tone}/10 text-${tone}`}>
        <Icon className="h-5 w-5" />
      </div>
      <div>
        <div className="text-xs uppercase tracking-wider text-muted-foreground">{label}</div>
        <div className="font-display text-2xl font-semibold">{value}</div>
      </div>
    </div>
  );
}
