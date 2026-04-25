import { useEffect, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { api } from "@/services/api";
import { Bot, Crown, Gavel, ShieldAlert } from "lucide-react";

const STATUS_TONE: Record<string, any> = { active: "success", warning: "warning", paused: "neutral" };

export default function Agents() {
  const [agents, setAgents] = useState<any[]>([]);
  const [active, setActive] = useState<any | null>(null);
  useEffect(() => { api.getAgentStatus().then((a) => setAgents([...a])); }, []);

  const groups = Array.from(new Set(agents.map((a) => a.group)));

  return (
    <>
      <PageHeader eyebrow="AI Layer" title="AI Agents Center"
        description="Every AI agent in the Nirogidhara stack — health, last action, reward & penalty in one view."
      />

      {/* Hierarchy */}
      <div className="surface-elevated p-6 mb-8 bg-gradient-hero text-primary-foreground relative overflow-hidden">
        <div className="absolute -right-20 -top-20 h-60 w-60 rounded-full bg-accent/30 blur-3xl" />
        <h3 className="font-display text-xl font-semibold mb-5">Agent hierarchy</h3>
        <div className="grid lg:grid-cols-[auto_1fr_auto] items-center gap-4 relative">
          <div className="rounded-2xl bg-background/15 backdrop-blur p-4 border border-background/20 text-center min-w-[180px]">
            <Crown className="h-5 w-5 mx-auto mb-1 text-accent" />
            <div className="text-xs uppercase tracking-wider opacity-70">Director</div>
            <div className="font-display text-lg font-semibold">Prarit Sidana</div>
          </div>
          <div className="hidden lg:flex items-center gap-3">
            <div className="h-px flex-1 bg-background/30" />
            <div className="rounded-2xl bg-gradient-gold text-accent-foreground p-4 text-center min-w-[200px] shadow-glow">
              <Bot className="h-5 w-5 mx-auto mb-1" />
              <div className="text-xs uppercase tracking-wider opacity-80">Command</div>
              <div className="font-display text-lg font-semibold">CEO AI Agent</div>
              <div className="text-[11px] opacity-80">Executes within approved policy</div>
            </div>
            <div className="h-px flex-1 bg-background/30" />
          </div>
          <div className="rounded-2xl bg-background/15 backdrop-blur p-4 border border-warning/40 text-center min-w-[180px]">
            <Gavel className="h-5 w-5 mx-auto mb-1 text-warning" />
            <div className="text-xs uppercase tracking-wider opacity-70">Governance</div>
            <div className="font-display text-lg font-semibold">CAIO Agent</div>
            <div className="text-[11px] opacity-80">Audits — never executes</div>
          </div>
        </div>
      </div>

      {groups.map((g) => (
        <div key={g} className="mb-8">
          <h3 className="font-display text-lg font-semibold mb-3">{g}</h3>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {agents.filter((a) => a.group === g).map((a) => (
              <button key={a.id} onClick={() => setActive(a)} className="surface-card p-5 text-left hover:shadow-elevated transition-all group">
                <div className="flex items-start justify-between mb-3">
                  <div className="h-10 w-10 rounded-xl bg-gradient-emerald-soft grid place-items-center">
                    <Bot className="h-5 w-5 text-primary" />
                  </div>
                  <StatusPill tone={STATUS_TONE[a.status]}>{a.status}</StatusPill>
                </div>
                <div className="font-semibold text-sm">{a.name}</div>
                <div className="text-[11px] text-muted-foreground line-clamp-2 mt-0.5">{a.role}</div>
                <div className="mt-3 flex items-baseline justify-between">
                  <div><div className="text-[10px] uppercase tracking-wider text-muted-foreground">Health</div><div className="font-display text-xl font-semibold">{a.health}%</div></div>
                  <div className="text-right">
                    <div className="text-[10px] text-success">+{a.reward}</div>
                    <div className="text-[10px] text-destructive">−{a.penalty}</div>
                  </div>
                </div>
                <div className="h-1 rounded-full bg-muted mt-2 overflow-hidden">
                  <div className="h-full bg-gradient-to-r from-primary to-primary-glow" style={{ width: `${a.health}%` }} />
                </div>
              </button>
            ))}
          </div>
        </div>
      ))}

      <Sheet open={!!active} onOpenChange={() => setActive(null)}>
        <SheetContent className="sm:max-w-md w-full">
          {active && (
            <>
              <SheetHeader>
                <SheetTitle className="font-display text-2xl">{active.name}</SheetTitle>
                <SheetDescription>{active.role}</SheetDescription>
              </SheetHeader>
              <div className="mt-6 space-y-3">
                <Row label="Status"><StatusPill tone={STATUS_TONE[active.status]}>{active.status}</StatusPill></Row>
                <Row label="Health"><span className="font-display text-xl font-semibold">{active.health}%</span></Row>
                <Row label="Reward points"><span className="text-success font-semibold">+{active.reward}</span></Row>
                <Row label="Penalty points"><span className="text-destructive font-semibold">−{active.penalty}</span></Row>
                <Row label="Last action"><span className="text-sm">{active.lastAction}</span></Row>
                {active.critical && (
                  <div className="rounded-xl bg-destructive/10 border border-destructive/20 p-3 text-sm text-destructive">
                    <ShieldAlert className="h-4 w-4 inline mr-1.5" />Critical alert raised — escalated to Prarit.
                  </div>
                )}
                <div className="flex gap-2 pt-2">
                  <Button variant="outline" className="flex-1">Pause</Button>
                  <Button className="flex-1 bg-gradient-hero text-primary-foreground">View logs</Button>
                </div>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </>
  );
}

function Row({ label, children }: any) {
  return (
    <div className="flex items-center justify-between rounded-xl bg-muted/40 p-3">
      <span className="text-xs uppercase tracking-wider text-muted-foreground">{label}</span>
      {children}
    </div>
  );
}