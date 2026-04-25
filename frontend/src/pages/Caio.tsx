import { PageHeader } from "@/components/PageHeader";
import { StatusPill, toneForStatus } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { api } from "@/services/api";
import type { CaioAudit } from "@/types/domain";
import { AlertTriangle, BookOpen, Gavel, ShieldAlert, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { useEffect, useState } from "react";

export default function Caio() {
  const [audits, setAudits] = useState<CaioAudit[]>([]);

  useEffect(() => { api.getCaioAudits().then(setAudits); }, []);

  return (
    <>
      <PageHeader eyebrow="AI Layer" title="CAIO Audit Center"
        description="Governance, audit and continuous improvement layer for every AI agent."
        actions={<Button variant="destructive" onClick={() => toast.error("Critical alert sent to Prarit")}><ShieldAlert className="h-4 w-4 mr-1.5" />Critical alert to Prarit</Button>}
      />

      <div className="surface-elevated p-6 mb-6 bg-gradient-emerald-soft border-warning/40 border-l-4">
        <div className="flex items-start gap-3">
          <Gavel className="h-6 w-6 text-warning mt-1" />
          <div>
            <h3 className="font-display text-lg font-semibold">CAIO never executes business actions.</h3>
            <p className="text-sm text-muted-foreground mt-1 max-w-3xl">
              CAIO Agent only monitors, audits, trains, suggests, improves prompts/playbooks, detects hallucination, detects weak learning, detects compliance failure, reports to CEO AI, and alerts Prarit for critical issues. <strong>Execution approval always flows through CEO AI Agent.</strong>
            </p>
          </div>
        </div>
      </div>

      <div className="grid sm:grid-cols-4 gap-4 mb-6">
        {[
          { label: "Open audits", value: audits.length, tone: "warning" },
          { label: "Critical", value: audits.filter((a) => a.severity === "Critical").length, tone: "danger" },
          { label: "High", value: audits.filter((a) => a.severity === "High").length, tone: "warning" },
          { label: "Approved this week", value: 7, tone: "success" },
        ].map((s) => (
          <div key={s.label} className="surface-card p-5">
            <div className="text-xs uppercase tracking-wider text-muted-foreground">{s.label}</div>
            <div className={`font-display text-3xl font-semibold mt-1 text-${s.tone}`}>{s.value}</div>
          </div>
        ))}
      </div>

      <div className="surface-card overflow-hidden">
        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
          <h3 className="font-display text-lg font-semibold">Agent audit queue</h3>
          <StatusPill tone="info">Updated live</StatusPill>
        </div>
        <div className="divide-y divide-border">
          {audits.map((a, i) => (
            <div key={i} className="p-5 hover:bg-muted/30 grid lg:grid-cols-[1fr_auto] gap-4">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <StatusPill tone={a.severity === "Critical" ? "danger" : a.severity === "High" ? "warning" : a.severity === "Medium" ? "info" : "neutral"}>
                    <AlertTriangle className="h-3 w-3 mr-0.5" />{a.severity}
                  </StatusPill>
                  <div className="font-medium">{a.agent}</div>
                </div>
                <div className="text-sm text-muted-foreground"><strong className="text-foreground">Issue:</strong> {a.issue}</div>
                <div className="text-sm text-muted-foreground mt-1"><Wand2 className="h-3.5 w-3.5 inline mr-1 text-accent" /><strong className="text-foreground">Suggestion:</strong> {a.suggestion}</div>
              </div>
              <div className="flex flex-col items-end gap-2">
                <StatusPill tone={toneForStatus(a.status)}>{a.status}</StatusPill>
                <div className="flex gap-1.5">
                  <Button size="sm" variant="outline"><BookOpen className="h-3.5 w-3.5 mr-1" />View evidence</Button>
                  <Button size="sm" className="bg-gradient-hero text-primary-foreground">Send to CEO AI</Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
