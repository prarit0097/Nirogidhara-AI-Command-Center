import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/services/api";
import type { CeoBriefing } from "@/types/domain";
import { AlertTriangle, ArrowRight, Check, Send, Sparkles, X, HelpCircle } from "lucide-react";
import { toast } from "sonner";
import { useEffect, useState } from "react";

export default function CeoAi() {
  const [decided, setDecided] = useState<Record<string, "approved" | "rejected" | "more">>({});
  const [q, setQ] = useState("");
  const [briefing, setBriefing] = useState<CeoBriefing | null>(null);

  useEffect(() => { api.getCeoBriefing().then(setBriefing); }, []);

  if (!briefing) return <div className="h-96 grid place-items-center text-muted-foreground">Loading CEO AI briefing...</div>;

  return (
    <>
      <PageHeader eyebrow="AI Layer" title="CEO AI Briefing"
        description="Daily business command. CEO AI executes within approved policy and reports straight to Prarit."
      />

      <div className="surface-elevated overflow-hidden mb-6 relative">
        <div className="absolute inset-0 bg-gradient-hero" />
        <div className="absolute -right-16 -top-20 h-72 w-72 rounded-full bg-accent/40 blur-3xl" />
        <div className="relative p-8 text-primary-foreground">
          <div className="inline-flex items-center gap-2 text-[11px] uppercase tracking-[0.22em] font-semibold text-accent mb-3">
            <Sparkles className="h-3.5 w-3.5" /> {briefing.date}
          </div>
          <h2 className="font-display text-3xl lg:text-4xl font-semibold text-balance leading-tight max-w-3xl">
            {briefing.headline}
          </h2>
          <p className="mt-3 text-primary-foreground/80 text-[15px] max-w-3xl leading-relaxed">{briefing.summary}</p>
        </div>
      </div>

      {/* Recommendations */}
      <h3 className="font-display text-xl font-semibold mb-3">Recommended actions</h3>
      <div className="grid lg:grid-cols-3 gap-4 mb-8">
        {briefing.recommendations.map((r) => {
          const state = decided[r.id];
          return (
            <div key={r.id} className="surface-card p-5 flex flex-col">
              <StatusPill tone="accent">{r.requires}</StatusPill>
              <div className="font-display text-lg font-semibold mt-3">{r.title}</div>
              <p className="text-sm text-muted-foreground mt-1.5 flex-1">{r.reason}</p>
              <div className="rounded-lg bg-success/10 border border-success/20 p-2.5 mt-3 text-xs text-success">
                Impact · {r.impact}
              </div>
              {state ? (
                <div className="mt-4 text-center text-sm font-medium">
                  {state === "approved" && <span className="text-success">✓ Approved</span>}
                  {state === "rejected" && <span className="text-destructive">✗ Rejected</span>}
                  {state === "more" && <span className="text-info">⏳ More data requested</span>}
                </div>
              ) : (
                <div className="grid grid-cols-3 gap-1.5 mt-4">
                  <Button size="sm" className="bg-success hover:bg-success/90 text-success-foreground" onClick={() => { setDecided((d) => ({ ...d, [r.id]: "approved" })); toast.success("Approved"); }}><Check className="h-3.5 w-3.5" /></Button>
                  <Button size="sm" variant="outline" onClick={() => { setDecided((d) => ({ ...d, [r.id]: "more" })); toast.info("Requested more data"); }}><HelpCircle className="h-3.5 w-3.5" /></Button>
                  <Button size="sm" variant="outline" className="text-destructive hover:text-destructive" onClick={() => { setDecided((d) => ({ ...d, [r.id]: "rejected" })); toast.error("Rejected"); }}><X className="h-3.5 w-3.5" /></Button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="grid lg:grid-cols-2 gap-6 mb-8">
        <div className="surface-card p-6 border-l-4 border-l-warning">
          <h3 className="font-display text-lg font-semibold mb-3"><AlertTriangle className="h-4 w-4 inline mr-1.5 text-warning" />Today's alerts</h3>
          <ul className="space-y-2 text-sm">
            {briefing.alerts.map((a, i) => (
              <li key={i} className="flex gap-2 items-start"><span className="text-warning mt-1">•</span><span>{a}</span></li>
            ))}
          </ul>
        </div>
        <div className="surface-card p-6 border-l-4 border-l-accent">
          <h3 className="font-display text-lg font-semibold mb-3">CEO AI role</h3>
          <ul className="space-y-2 text-sm text-muted-foreground">
            <li className="flex gap-2"><ArrowRight className="h-3.5 w-3.5 mt-1 text-accent" /><span>Business command & execution within approved policy</span></li>
            <li className="flex gap-2"><ArrowRight className="h-3.5 w-3.5 mt-1 text-accent" /><span>Reports to Prarit, distributes reward / penalty</span></li>
            <li className="flex gap-2"><ArrowRight className="h-3.5 w-3.5 mt-1 text-accent" /><span>Prioritizes growth, profit, safety & compliance</span></li>
            <li className="flex gap-2"><ArrowRight className="h-3.5 w-3.5 mt-1 text-accent" /><span>Critical / new actions require human approval</span></li>
          </ul>
        </div>
      </div>

      <div className="surface-elevated p-6">
        <h3 className="font-display text-xl font-semibold mb-3 flex items-center gap-2"><Sparkles className="h-5 w-5 text-accent" />Ask CEO AI</h3>
        <div className="flex gap-2">
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. What is the best lever to lift delivered profit this week?" className="bg-muted/50 border-transparent" />
          <Button className="bg-gradient-hero text-primary-foreground" onClick={() => { setQ(""); toast.success("CEO AI is preparing your answer…"); }}><Send className="h-4 w-4" /></Button>
        </div>
        <div className="flex flex-wrap gap-2 mt-3">
          {["What if we increase ad budget by 20%?", "Which agent is hurting net profit?", "Best COD policy for Bihar?"].map((s) => (
            <button key={s} onClick={() => setQ(s)} className="text-xs px-3 py-1.5 rounded-full bg-muted hover:bg-muted/70 text-muted-foreground">
              {s}
            </button>
          ))}
        </div>
      </div>
    </>
  );
}
