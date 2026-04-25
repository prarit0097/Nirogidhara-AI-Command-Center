import { PageHeader } from "@/components/PageHeader";
import { StatusPill, toneForStatus } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { api } from "@/services/api";
import type { LearningRecording } from "@/types/domain";
import { AlertTriangle, FileAudio, Mic, Upload } from "lucide-react";
import { toast } from "sonner";
import { useEffect, useState } from "react";

const STAGES = ["Recording", "Transcript", "Speaker Separation", "QA Scoring", "Compliance Review", "CAIO Audit", "Approved Learning", "Prompt Update", "Sandbox Test", "CEO Approval", "Live Update"];

export default function Learning() {
  const [recordings, setRecordings] = useState<LearningRecording[]>([]);

  useEffect(() => { api.getHumanCallLearningItems().then(setRecordings); }, []);

  return (
    <>
      <PageHeader eyebrow="Governance" title="Human Call Learning Studio"
        description="Turn the best human calls into safe, doctor-approved AI training. Nothing trains live AI without QA, compliance and CEO approval."
      />

      <div className="surface-elevated p-6 mb-6 border-l-4 border-l-destructive bg-destructive/5">
        <div className="flex items-start gap-3">
          <AlertTriangle className="h-6 w-6 text-destructive mt-0.5" />
          <div>
            <h3 className="font-display text-lg font-semibold text-destructive">Human recordings never auto-train live AI.</h3>
            <p className="text-sm text-muted-foreground mt-1">They must pass QA → Compliance → CAIO Audit → Sandbox → CEO approval before any prompt or playbook changes go live.</p>
          </div>
        </div>
      </div>

      <div className="surface-card p-8 mb-6 bg-gradient-leaf border-2 border-dashed border-primary/30">
        <div className="text-center">
          <div className="h-14 w-14 rounded-2xl bg-primary/10 grid place-items-center mx-auto mb-3">
            <Upload className="h-6 w-6 text-primary" />
          </div>
          <h3 className="font-display text-xl font-semibold">Upload call recording</h3>
          <p className="text-sm text-muted-foreground mt-1">Drag & drop .mp3 / .wav up to 200 MB. Speech-to-text & speaker separation runs automatically.</p>
          <Button className="mt-4 bg-gradient-hero text-primary-foreground" onClick={() => toast.success("Mock upload queued for transcript")}>
            <Mic className="h-4 w-4 mr-1.5" />Choose file
          </Button>
        </div>
      </div>

      <div className="surface-card p-6 mb-6">
        <h3 className="font-display text-lg font-semibold mb-4">Learning workflow</h3>
        <div className="flex flex-wrap items-center gap-2">
          {STAGES.map((s, i, arr) => (
            <div key={s} className="flex items-center gap-2">
              <span className={`px-3 py-1.5 rounded-full text-xs font-medium ${i < 4 ? "bg-success text-success-foreground" : i === 4 ? "bg-warning text-warning-foreground" : "bg-muted text-foreground"}`}>{s}</span>
              {i < arr.length - 1 && <span className="text-muted-foreground">→</span>}
            </div>
          ))}
        </div>
      </div>

      <div className="surface-card overflow-hidden">
        <div className="px-6 py-4 border-b border-border"><h3 className="font-display text-lg font-semibold">Recordings in pipeline</h3></div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[800px]">
            <thead className="bg-muted/30 text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left font-medium px-6 py-3">ID</th>
                <th className="text-left font-medium py-3">Agent</th>
                <th className="text-left font-medium py-3">Duration</th>
                <th className="text-left font-medium py-3">Date</th>
                <th className="text-left font-medium py-3">Stage</th>
                <th className="text-left font-medium py-3">QA</th>
                <th className="text-left font-medium py-3">Compliance</th>
                <th className="text-left font-medium px-6 py-3">Outcome</th>
              </tr>
            </thead>
            <tbody>
              {recordings.map((r) => (
                <tr key={r.id} className="border-t border-border/60 hover:bg-muted/20">
                  <td className="px-6 py-3 font-mono text-xs"><FileAudio className="h-3.5 w-3.5 inline mr-1.5 text-muted-foreground" />{r.id}</td>
                  <td className="py-3">{r.agent}</td>
                  <td className="py-3 tabular-nums">{r.duration}</td>
                  <td className="py-3 text-muted-foreground">{r.date}</td>
                  <td className="py-3"><StatusPill tone={toneForStatus(r.stage)}>{r.stage}</StatusPill></td>
                  <td className="py-3">{r.qa ? <StatusPill tone={r.qa > 85 ? "success" : "warning"}>{r.qa}</StatusPill> : <span className="text-muted-foreground">—</span>}</td>
                  <td className="py-3"><StatusPill tone={r.compliance === "Pass" ? "success" : r.compliance === "—" ? "neutral" : "warning"}>{r.compliance}</StatusPill></td>
                  <td className="px-6 py-3">{r.outcome}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
