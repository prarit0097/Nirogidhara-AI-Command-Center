import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, isApiError } from "@/services/api";
import type {
  AiCopilotSourceType,
  AiCopilotStatusResponse,
  AiCopilotSuggestion,
  AiCopilotSuggestionType,
} from "@/types/domain";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Lock,
  ShieldCheck,
  Sparkles,
  XCircle,
} from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

const STATUS_STYLES: Record<string, string> = {
  draft: "bg-muted text-muted-foreground",
  pending_review: "bg-warning/20 text-warning",
  approved: "bg-success/15 text-success",
  rejected: "bg-destructive/15 text-destructive",
  applied_internal: "bg-primary/15 text-primary",
};

const SUGGESTION_TYPES: { value: AiCopilotSuggestionType; label: string }[] = [
  { value: "lead_summary", label: "Lead / customer summary" },
  { value: "call_priority", label: "Call priority" },
  { value: "call_script", label: "Call script draft" },
  { value: "objection_handling", label: "Objection handling" },
  { value: "compliance_risk", label: "Compliance risk review" },
  { value: "pilot_recommendation", label: "Pilot recommendation" },
  { value: "director_briefing", label: "Director briefing" },
  { value: "whatsapp_draft", label: "WhatsApp draft (not sent)" },
  { value: "payment_followup_draft", label: "Payment follow-up draft (not sent)" },
  { value: "rto_rescue_draft", label: "RTO rescue draft (not sent)" },
];

const SOURCE_TYPES: { value: AiCopilotSourceType; label: string }[] = [
  { value: "manual", label: "Manual / none" },
  { value: "lead", label: "Lead" },
  { value: "customer", label: "Customer" },
  { value: "order", label: "Order" },
  { value: "imported_queue_item", label: "Imported queue item" },
  { value: "pilot_plan", label: "Pilot plan" },
  { value: "pilot_task", label: "Pilot task" },
];

export default function AiCopilot() {
  const [status, setStatus] = useState<AiCopilotStatusResponse | null>(null);
  const [suggestions, setSuggestions] = useState<AiCopilotSuggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [errored, setErrored] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sType, setSType] = useState<AiCopilotSuggestionType>("director_briefing");
  const [sourceType, setSourceType] = useState<AiCopilotSourceType>("manual");
  const [sourceId, setSourceId] = useState("");
  const [text, setText] = useState("");

  const load = () => {
    setLoading(true);
    Promise.all([
      api.getAiCopilotStatus().then(setStatus),
      api
        .getAiCopilotSuggestions()
        .then((r) => setSuggestions(r.items))
        .catch(() => setSuggestions([])),
    ])
      .catch(() => {
        setStatus(null);
        setErrored(true);
      })
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleGenerate = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api.generateAiCopilotSuggestion({
        suggestionType: sType,
        sourceType,
        sourceId: sourceId.trim() || undefined,
        text: text.trim() || undefined,
      });
      toast.success("AI suggestion generated (internal, pending review).");
      setText("");
      load();
    } catch (err) {
      if (isApiError(err)) {
        toast.error(`Generate failed (HTTP ${err.httpStatus}).`);
      } else {
        toast.error("Generate failed. Please retry.");
      }
    } finally {
      setBusy(false);
    }
  };

  const handleReview = async (s: AiCopilotSuggestion, action: "approve" | "reject" | "apply_internal") => {
    if (busy) return;
    setBusy(true);
    try {
      await api.reviewAiCopilotSuggestion(s.id, { action });
      toast.success(`Suggestion ${action.replace("_", " ")} (internal only).`);
      load();
    } catch (err) {
      if (isApiError(err)) {
        toast.error(`Review failed (HTTP ${err.httpStatus}).`);
      } else {
        toast.error("Review failed. Please retry.");
      }
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="h-96 grid place-items-center text-muted-foreground">
        Loading AI Copilot...
      </div>
    );
  }

  if (errored || !status) {
    return (
      <div data-testid="ai-copilot-page">
        <PageHeader eyebrow="Operations" title="AI Copilot Center" />
        <div
          data-testid="ai-copilot-error"
          className="surface-elevated p-6 text-destructive text-[14px]"
        >
          Could not load AI Copilot. Please retry.
        </div>
      </div>
    );
  }

  return (
    <div data-testid="ai-copilot-page">
      <PageHeader
        eyebrow="Operations"
        title="AI Copilot Center"
        description="Internal AI copilot — analyze, draft, recommend, and score. A human approves before any business action. No live autonomous AI."
      />

      {/* Safety banner */}
      <div
        data-testid="ai-copilot-safety-copy"
        className="mb-6 flex items-start gap-2 rounded-xl border border-border bg-muted/40 px-4 py-3 text-[13px] text-muted-foreground"
      >
        <ShieldCheck className="h-4 w-4 mt-0.5 shrink-0 text-success" />
        <span>
          Internal copilot only — no live autonomous execution. Generating a
          suggestion NEVER sends WhatsApp, takes a payment, books a shipment,
          places a call, or invokes a live AI provider. Every suggestion is
          deterministic ({status.aiMode}) and requires human approval; live
          provider actions stay locked behind a future Director live gate.
        </span>
      </div>

      {/* AI safety status chips */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6" data-testid="ai-copilot-status">
        <Chip label="AI" value={status.aiPaused ? "Paused" : "Running"} tone={status.aiPaused ? "success" : "warning"} />
        <Chip label="Sandbox" value={status.sandboxOn ? "ON" : "OFF"} tone="success" />
        <Chip label="AI mode" value={status.aiMode} tone="success" />
        <Chip label="Live autonomous" value={status.liveAutonomousExecutionLocked ? "Locked" : "Open"} tone={status.liveAutonomousExecutionLocked ? "success" : "danger"} />
        <Chip label="Live provider" value={status.liveProviderStatus} tone="warning" />
        <Chip label="Provider" value={status.aiProvider} tone="warning" />
        <Chip label="Human approval" value={status.humanApprovalRequired ? "Required" : "Off"} tone="success" />
        <Chip label="Provider call" value={status.noProviderCallMade ? "None" : "Made"} tone={status.noProviderCallMade ? "success" : "danger"} />
      </div>

      {/* Generate */}
      <div className="surface-elevated p-6 mb-6" data-testid="ai-copilot-generate-form">
        <h2 className="font-display text-lg font-semibold flex items-center gap-2 mb-3">
          <Sparkles className="h-5 w-5 text-accent" /> Generate AI suggestion
        </h2>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 items-end">
          <div>
            <label className="text-[11px] uppercase tracking-wider text-muted-foreground block">Type</label>
            <select
              data-testid="ai-copilot-type"
              aria-label="Suggestion type"
              value={sType}
              onChange={(e) => setSType(e.target.value as AiCopilotSuggestionType)}
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-[13.5px]"
            >
              {SUGGESTION_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[11px] uppercase tracking-wider text-muted-foreground block">Source</label>
            <select
              data-testid="ai-copilot-source"
              aria-label="Source type"
              value={sourceType}
              onChange={(e) => setSourceType(e.target.value as AiCopilotSourceType)}
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-[13.5px]"
            >
              {SOURCE_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[11px] uppercase tracking-wider text-muted-foreground block">Source id (optional)</label>
            <Input
              data-testid="ai-copilot-source-id"
              value={sourceId}
              onChange={(e) => setSourceId(e.target.value)}
              disabled={busy}
              placeholder="e.g. NRG-1234"
            />
          </div>
          <Button data-testid="ai-copilot-generate-button" onClick={handleGenerate} disabled={busy}>
            {busy ? "Generating…" : "Generate suggestion"}
          </Button>
        </div>
        {sType === "compliance_risk" && (
          <div className="mt-3">
            <label className="text-[11px] uppercase tracking-wider text-muted-foreground block">Text to review (optional)</label>
            <Input
              data-testid="ai-copilot-text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              disabled={busy}
              placeholder="Paste internal draft text to scan for compliance risk"
            />
          </div>
        )}
        <p className="text-[11px] text-muted-foreground mt-2">
          The copilot generates deterministically and never sends anything. Suggestions land in the queue below for human review.
        </p>
      </div>

      {/* Suggestions queue + review */}
      <div className="surface-elevated p-6" data-testid="ai-copilot-queue">
        <h3 className="font-display text-lg font-semibold flex items-center gap-2 mb-4">
          <Bot className="h-5 w-5 text-accent" /> AI suggestions ({suggestions.length})
        </h3>
        {suggestions.length === 0 ? (
          <p data-testid="ai-copilot-empty" className="text-muted-foreground text-[14px]">
            No AI suggestions yet. Generate one above.
          </p>
        ) : (
          <div className="space-y-3">
            {suggestions.map((s) => (
              <div
                key={s.id}
                data-testid={`ai-copilot-suggestion-${s.id}`}
                className="rounded-lg border border-border bg-muted/20 px-4 py-3"
              >
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div className="min-w-0">
                    <div className="font-medium">{s.title}</div>
                    <div className="text-[12px] text-muted-foreground">
                      {s.suggestionType.replace(/_/g, " ")} · {s.sourceType}
                      {s.sourceId ? ` · ${s.sourceId}` : ""} · mode {s.aiMode}
                    </div>
                  </div>
                  <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase ${STATUS_STYLES[s.status] ?? STATUS_STYLES.draft}`}>
                    {s.status.replace(/_/g, " ")}
                  </span>
                </div>
                <p className="text-[13px] text-muted-foreground mt-2">{s.summary}</p>
                {s.recommendation && (
                  <p className="text-[13px] mt-1"><span className="text-muted-foreground">Recommendation: </span>{s.recommendation}</p>
                )}
                {s.riskFlags.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-2" data-testid={`ai-copilot-risk-${s.id}`}>
                    {s.riskFlags.map((r) => (
                      <span key={r} className="inline-flex items-center gap-1 rounded-full bg-warning/15 text-warning px-2 py-0.5 text-[11px]">
                        <AlertTriangle className="h-3 w-3" /> {r}
                      </span>
                    ))}
                  </div>
                )}
                {s.status === "pending_review" && (
                  <div className="flex flex-wrap gap-1.5 mt-3">
                    <Button data-testid={`ai-copilot-approve-${s.id}`} variant="outline" size="sm" disabled={busy} onClick={() => handleReview(s, "approve")}>
                      <CheckCircle2 className="h-3.5 w-3.5 mr-1" /> Approve (internal)
                    </Button>
                    <Button data-testid={`ai-copilot-reject-${s.id}`} variant="outline" size="sm" disabled={busy} onClick={() => handleReview(s, "reject")}>
                      <XCircle className="h-3.5 w-3.5 mr-1" /> Reject
                    </Button>
                    <Button data-testid={`ai-copilot-apply-${s.id}`} variant="outline" size="sm" disabled={busy} onClick={() => handleReview(s, "apply_internal")}>
                      Mark applied (internal only)
                    </Button>
                  </div>
                )}
                <p className="text-[11px] text-muted-foreground mt-2 flex items-center gap-1.5">
                  <Lock className="h-3 w-3" /> External action allowed: {String(s.externalActionAllowed)} · taken: {String(s.externalActionTaken)} · provider call: {String(s.providerCallMade)}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Chip({ label, value, tone }: { label: string; value: string; tone?: "success" | "warning" | "danger" }) {
  const toneClass =
    tone === "success" ? "text-success" : tone === "warning" ? "text-warning" : tone === "danger" ? "text-destructive" : "text-foreground";
  return (
    <div className="rounded-lg border border-border bg-muted/30 px-3 py-2">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={`text-[14px] font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}
