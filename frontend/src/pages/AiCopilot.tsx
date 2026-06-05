import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, isApiError } from "@/services/api";
import type {
  AiActionType,
  AiApprovedAction,
  AiCopilotSourceType,
  AiCopilotStatusResponse,
  AiCopilotSuggestion,
  AiCopilotSuggestionType,
  AiMyWorkSummary,
  AiWorkboardAnalytics,
  AiWorkboardAttentionItem,
  AiWorkboardSummary,
  AiWorkPermissions,
} from "@/types/domain";
import {
  AlertCircle,
  AlertTriangle,
  BarChart3,
  Bot,
  CheckCircle2,
  ClipboardList,
  Clock,
  ListTodo,
  Lock,
  ShieldCheck,
  Sparkles,
  UserCheck,
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

const ACTION_TYPES: { value: AiActionType; label: string }[] = [
  { value: "create_calling_followup_task", label: "Calling follow-up task" },
  { value: "create_qa_review_task", label: "QA / compliance review task" },
  { value: "create_pilot_task", label: "Pilot task" },
  { value: "create_customer_note", label: "Customer note" },
  { value: "create_order_note", label: "Order note" },
  { value: "create_callback_item", label: "Callback reminder item" },
  { value: "create_rto_review_task", label: "RTO review task" },
  { value: "create_payment_followup_task", label: "Payment follow-up task" },
  { value: "create_dispatch_review_task", label: "Dispatch review task" },
  { value: "create_director_review_item", label: "Director review item" },
];

const ACTION_STATUS_STYLES: Record<string, string> = {
  pending_internal_action: "bg-warning/20 text-warning",
  applied_internal: "bg-success/15 text-success",
  rejected: "bg-destructive/15 text-destructive",
  cancelled: "bg-muted text-muted-foreground",
  failed: "bg-destructive/15 text-destructive",
};

// ---------- Phase 16K — Department Action Workboard ----------

const DEPARTMENTS: { value: string; label: string }[] = [
  { value: "calling", label: "Calling" },
  { value: "confirmation", label: "Confirmation" },
  { value: "qa_compliance", label: "QA / Compliance" },
  { value: "finance_accounts", label: "Finance / Accounts" },
  { value: "dispatch_warehouse", label: "Dispatch / Warehouse" },
  { value: "delivery_rto", label: "Delivery / RTO" },
  { value: "director_office", label: "Director Office" },
  { value: "data_ops", label: "Data Ops" },
  { value: "ai_governance", label: "AI Governance" },
];

const WORK_STATUS_STYLES: Record<string, string> = {
  unassigned: "bg-muted text-muted-foreground",
  assigned: "bg-primary/15 text-primary",
  in_progress: "bg-accent/15 text-accent",
  blocked: "bg-destructive/15 text-destructive",
  completed_internal: "bg-success/15 text-success",
  rejected: "bg-destructive/15 text-destructive",
  cancelled: "bg-muted text-muted-foreground",
};

const SLA_STYLES: Record<string, string> = {
  no_due_date: "bg-muted text-muted-foreground",
  on_track: "bg-success/15 text-success",
  due_soon: "bg-warning/20 text-warning",
  overdue: "bg-destructive/15 text-destructive",
};

type WorkboardVerb =
  | "claim" | "start" | "unblock" | "complete";

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
  const [actions, setActions] = useState<AiApprovedAction[]>([]);
  const [actionType, setActionType] = useState<AiActionType>("create_qa_review_task");

  // Phase 16K — department workboard
  const [workboard, setWorkboard] = useState<AiApprovedAction[]>([]);
  const [wbSummary, setWbSummary] = useState<AiWorkboardSummary | null>(null);
  const [attention, setAttention] = useState<AiWorkboardAttentionItem[]>([]);
  const [wbDept, setWbDept] = useState("");
  const [wbStatus, setWbStatus] = useState("");
  const [wbPriority, setWbPriority] = useState("");
  const [wbSla, setWbSla] = useState("");
  const [wbSearch, setWbSearch] = useState("");

  // Phase 16L — scoped permissions + My Work queue
  const [myPerms, setMyPerms] = useState<AiWorkPermissions | null>(null);
  const [myWork, setMyWork] = useState<AiApprovedAction[]>([]);
  const [myWorkSummary, setMyWorkSummary] = useState<AiMyWorkSummary | null>(null);

  // Phase 16M — workboard analytics + SLA throughput (read-only)
  const [analytics, setAnalytics] = useState<AiWorkboardAnalytics | null>(null);

  const loadActions = () => {
    api
      .getAiActionQueue()
      .then((r) => setActions(r.items))
      .catch(() => setActions([]));
  };

  const loadMyWork = () => {
    api.getAiMyWork().then((r) => {
      setMyWork(r.items);
      if (r.myPermissions) setMyPerms(r.myPermissions);
    }).catch(() => setMyWork([]));
    api.getAiMyWorkSummary().then(setMyWorkSummary).catch(() => setMyWorkSummary(null));
  };

  const loadAnalytics = () => {
    api.getAiWorkboardAnalytics().then(setAnalytics).catch(() => setAnalytics(null));
  };

  const loadWorkboard = () => {
    const params: Record<string, string> = {};
    if (wbDept) params.department = wbDept;
    if (wbStatus) params.workStatus = wbStatus;
    if (wbPriority) params.priority = wbPriority;
    if (wbSla) params.slaStatus = wbSla;
    if (wbSearch.trim()) params.search = wbSearch.trim();
    api.getAiWorkboard(params).then((r) => {
      setWorkboard(r.items);
      if (r.myPermissions) setMyPerms(r.myPermissions);
    }).catch(() => setWorkboard([]));
    api.getAiWorkboardSummary().then(setWbSummary).catch(() => setWbSummary(null));
    api.getAiWorkboardDirectorAttention().then((r) => setAttention(r.items)).catch(() => setAttention([]));
    loadMyWork();
    loadAnalytics();
  };

  const load = () => {
    setLoading(true);
    Promise.all([
      api.getAiCopilotStatus().then(setStatus),
      api
        .getAiCopilotSuggestions()
        .then((r) => setSuggestions(r.items))
        .catch(() => setSuggestions([])),
      api
        .getAiActionQueue()
        .then((r) => setActions(r.items))
        .catch(() => setActions([])),
      api.getAiWorkboard().then((r) => {
        setWorkboard(r.items);
        if (r.myPermissions) setMyPerms(r.myPermissions);
      }).catch(() => setWorkboard([])),
      api.getAiWorkboardSummary().then(setWbSummary).catch(() => setWbSummary(null)),
      api
        .getAiWorkboardDirectorAttention()
        .then((r) => setAttention(r.items))
        .catch(() => setAttention([])),
      api.getAiMyWork().then((r) => {
        setMyWork(r.items);
        if (r.myPermissions) setMyPerms(r.myPermissions);
      }).catch(() => setMyWork([])),
      api.getAiMyWorkSummary().then(setMyWorkSummary).catch(() => setMyWorkSummary(null)),
      api.getAiWorkboardAnalytics().then(setAnalytics).catch(() => setAnalytics(null)),
    ])
      .catch(() => {
        setStatus(null);
        setErrored(true);
      })
      .finally(() => setLoading(false));
  };

  const refreshWorkboard = () => {
    loadWorkboard();
  };

  const handleWorkboardError = (err: unknown, label: string) => {
    if (isApiError(err)) {
      toast.error(`${label} failed (HTTP ${err.httpStatus}).`);
    } else {
      toast.error(`${label} failed. Please retry.`);
    }
  };

  const handleAssign = async (action: AiApprovedAction, department: string) => {
    if (busy) return;
    if (!department) {
      toast.error("Pick a department to assign.");
      return;
    }
    setBusy(true);
    try {
      await api.assignAiAction(action.id, { department: department as never });
      toast.success("Assigned (internal only).");
      refreshWorkboard();
    } catch (err) {
      handleWorkboardError(err, "Assign");
    } finally {
      setBusy(false);
    }
  };

  const handleReassign = async (action: AiApprovedAction, department: string) => {
    if (busy) return;
    if (!department) {
      toast.error("Pick a department to reassign.");
      return;
    }
    setBusy(true);
    try {
      await api.reassignAiAction(action.id, { department: department as never });
      toast.success("Reassigned (internal only).");
      refreshWorkboard();
    } catch (err) {
      handleWorkboardError(err, "Reassign");
    } finally {
      setBusy(false);
    }
  };

  const handleBlock = async (action: AiApprovedAction, reason: string) => {
    if (busy) return;
    if (!reason.trim()) {
      toast.error("A blocker reason is required.");
      return;
    }
    setBusy(true);
    try {
      await api.blockAiAction(action.id, { reason: reason.trim() });
      toast.success("Blocked (internal only).");
      refreshWorkboard();
    } catch (err) {
      handleWorkboardError(err, "Block");
    } finally {
      setBusy(false);
    }
  };

  const handleNote = async (action: AiApprovedAction, note: string) => {
    if (busy) return;
    if (!note.trim()) {
      toast.error("Enter a note.");
      return;
    }
    setBusy(true);
    try {
      await api.addAiActionNote(action.id, { note: note.trim() });
      toast.success("Note added (internal only).");
      refreshWorkboard();
    } catch (err) {
      handleWorkboardError(err, "Add note");
    } finally {
      setBusy(false);
    }
  };

  const handleWorkboardVerb = async (action: AiApprovedAction, verb: WorkboardVerb) => {
    if (busy) return;
    setBusy(true);
    try {
      if (verb === "claim") await api.claimAiAction(action.id);
      else if (verb === "start") await api.startAiAction(action.id);
      else if (verb === "unblock") await api.unblockAiAction(action.id);
      else await api.completeInternalAiAction(action.id);
      toast.success(`Action ${verb === "complete" ? "completed (internal only)" : verb + "ed"}.`);
      refreshWorkboard();
    } catch (err) {
      handleWorkboardError(err, `Action ${verb}`);
    } finally {
      setBusy(false);
    }
  };

  const handleCreateAction = async (suggestion: AiCopilotSuggestion) => {
    if (busy) return;
    setBusy(true);
    try {
      await api.createAiActionFromSuggestion({
        suggestionId: suggestion.id,
        actionType,
      });
      toast.success("Internal action queued (no external action).");
      loadActions();
    } catch (err) {
      if (isApiError(err)) {
        toast.error(
          err.httpStatus === 409
            ? "Only an approved suggestion can become an internal action."
            : `Create action failed (HTTP ${err.httpStatus}).`,
        );
      } else {
        toast.error("Create action failed. Please retry.");
      }
    } finally {
      setBusy(false);
    }
  };

  const handleActionTransition = async (
    action: AiApprovedAction,
    kind: "apply" | "reject" | "cancel",
  ) => {
    if (busy) return;
    setBusy(true);
    try {
      if (kind === "apply") await api.applyAiAction(action.id);
      else if (kind === "reject") await api.rejectAiAction(action.id);
      else await api.cancelAiAction(action.id);
      toast.success(`Internal action ${kind === "apply" ? "applied (internal only)" : kind + "ed"}.`);
      loadActions();
    } catch (err) {
      if (isApiError(err)) {
        toast.error(`Action ${kind} failed (HTTP ${err.httpStatus}).`);
      } else {
        toast.error(`Action ${kind} failed. Please retry.`);
      }
    } finally {
      setBusy(false);
    }
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

  const approvedSuggestions = suggestions.filter((s) => s.status === "approved");

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

      {/* Phase 16J — Approved Action Queue */}
      <div className="surface-elevated p-6 mt-6" data-testid="ai-action-queue-section">
        <h3 className="font-display text-lg font-semibold flex items-center gap-2 mb-2">
          <ListTodo className="h-5 w-5 text-accent" /> Approved action queue
        </h3>
        <p
          data-testid="ai-action-safety-copy"
          className="text-[12px] text-muted-foreground mb-4"
        >
          Applying internal actions does not send WhatsApp, create payment links,
          book shipments, call customers, or invoke live AI providers. Every action
          is internal/DB-only.
        </p>

        {/* Create internal action from an approved suggestion */}
        <div className="rounded-lg border border-border bg-muted/20 px-4 py-3 mb-4">
          <div className="flex items-center gap-2 mb-2">
            <label className="text-[11px] uppercase tracking-wider text-muted-foreground">Action type</label>
            <select
              data-testid="ai-action-type"
              aria-label="Action type"
              value={actionType}
              onChange={(e) => setActionType(e.target.value as AiActionType)}
              className="h-9 rounded-md border border-input bg-background px-3 text-[13px]"
            >
              {ACTION_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>
          {approvedSuggestions.length === 0 ? (
            <p data-testid="ai-action-no-approved" className="text-[13px] text-muted-foreground">
              No approved suggestions yet. Approve a suggestion above to create an internal action.
            </p>
          ) : (
            <div className="space-y-1.5" data-testid="ai-action-approved-list">
              {approvedSuggestions.map((s) => (
                <div key={s.id} className="flex items-center justify-between gap-2 flex-wrap text-[13px]">
                  <span className="min-w-0 truncate">{s.title} <span className="text-muted-foreground">({s.suggestionType.replace(/_/g, " ")})</span></span>
                  <Button
                    data-testid={`ai-action-create-${s.id}`}
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    onClick={() => handleCreateAction(s)}
                  >
                    Create internal action
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* The internal action queue */}
        {actions.length === 0 ? (
          <p data-testid="ai-action-empty" className="text-muted-foreground text-[14px]">
            No internal actions yet.
          </p>
        ) : (
          <div className="space-y-3" data-testid="ai-action-list">
            {actions.map((a) => (
              <div
                key={a.id}
                data-testid={`ai-action-${a.id}`}
                className="rounded-lg border border-border bg-muted/20 px-4 py-3"
              >
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div className="min-w-0">
                    <div className="font-medium">{a.title}</div>
                    <div className="text-[12px] text-muted-foreground">
                      {a.actionType.replace(/_/g, " ")} · {a.assignedTeam || "unassigned"} · {a.priority}
                    </div>
                  </div>
                  <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase ${ACTION_STATUS_STYLES[a.status] ?? ACTION_STATUS_STYLES.cancelled}`}>
                    {a.status.replace(/_/g, " ")}
                  </span>
                </div>
                {a.status === "pending_internal_action" && (
                  <div className="flex flex-wrap gap-1.5 mt-3">
                    <Button data-testid={`ai-action-apply-${a.id}`} variant="outline" size="sm" disabled={busy} onClick={() => handleActionTransition(a, "apply")}>
                      <CheckCircle2 className="h-3.5 w-3.5 mr-1" /> Apply internal action
                    </Button>
                    <Button data-testid={`ai-action-reject-${a.id}`} variant="outline" size="sm" disabled={busy} onClick={() => handleActionTransition(a, "reject")}>
                      <XCircle className="h-3.5 w-3.5 mr-1" /> Reject action
                    </Button>
                    <Button data-testid={`ai-action-cancel-${a.id}`} variant="outline" size="sm" disabled={busy} onClick={() => handleActionTransition(a, "cancel")}>
                      Cancel action
                    </Button>
                  </div>
                )}
                <p className="text-[11px] text-muted-foreground mt-2 flex items-center gap-1.5">
                  <Lock className="h-3 w-3" /> external action allowed: {String(a.externalActionAllowed)} · provider action taken: {String(a.providerActionTaken)}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Phase 16K — Department Action Workboard */}
      <div className="surface-elevated p-6 mt-6" data-testid="ai-workboard-section">
        <h3 className="font-display text-lg font-semibold flex items-center gap-2 mb-2">
          <ClipboardList className="h-5 w-5 text-accent" /> Department action workboard
        </h3>
        <p
          data-testid="ai-workboard-safety-copy"
          className="text-[12px] text-muted-foreground mb-4"
        >
          Completing or updating a workboard action never sends WhatsApp, creates
          payment links, books shipments, calls customers, invokes Vapi, or calls a
          live AI provider. This is an internal execution tracker only.
        </p>

        {/* Summary cards */}
        {wbSummary && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5" data-testid="ai-workboard-summary">
            <SummaryCard label="Total" value={wbSummary.total} />
            <SummaryCard label="Unassigned" value={wbSummary.unassigned} />
            <SummaryCard label="Assigned" value={wbSummary.assigned} />
            <SummaryCard label="In progress" value={wbSummary.inProgress} tone="accent" />
            <SummaryCard label="Blocked" value={wbSummary.blocked} tone={wbSummary.blocked ? "danger" : undefined} />
            <SummaryCard label="Overdue" value={wbSummary.overdue} tone={wbSummary.overdue ? "danger" : undefined} />
            <SummaryCard label="Completed" value={wbSummary.completedInternal} tone="success" />
            <SummaryCard label="Director attention" value={wbSummary.directorAttention} tone={wbSummary.directorAttention ? "warning" : undefined} />
          </div>
        )}

        {/* Filters */}
        <div className="flex flex-wrap gap-2 items-end mb-4" data-testid="ai-workboard-filters">
          <select aria-label="Filter department" data-testid="ai-workboard-filter-department" value={wbDept} onChange={(e) => setWbDept(e.target.value)} className="h-9 rounded-md border border-input bg-background px-3 text-[13px]">
            <option value="">All departments</option>
            {DEPARTMENTS.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
          </select>
          <select aria-label="Filter status" data-testid="ai-workboard-filter-status" value={wbStatus} onChange={(e) => setWbStatus(e.target.value)} className="h-9 rounded-md border border-input bg-background px-3 text-[13px]">
            <option value="">All statuses</option>
            {["unassigned", "assigned", "in_progress", "blocked", "completed_internal"].map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}
          </select>
          <select aria-label="Filter priority" data-testid="ai-workboard-filter-priority" value={wbPriority} onChange={(e) => setWbPriority(e.target.value)} className="h-9 rounded-md border border-input bg-background px-3 text-[13px]">
            <option value="">All priorities</option>
            {["low", "normal", "high", "urgent"].map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
          <select aria-label="Filter SLA" data-testid="ai-workboard-filter-sla" value={wbSla} onChange={(e) => setWbSla(e.target.value)} className="h-9 rounded-md border border-input bg-background px-3 text-[13px]">
            <option value="">All SLA</option>
            {["no_due_date", "on_track", "due_soon", "overdue"].map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}
          </select>
          <Input data-testid="ai-workboard-search" value={wbSearch} onChange={(e) => setWbSearch(e.target.value)} placeholder="Search title" className="h-9 w-40" />
          <Button data-testid="ai-workboard-apply-filters" variant="outline" size="sm" onClick={refreshWorkboard} disabled={busy}>Apply</Button>
        </div>

        {/* Director attention */}
        {attention.length > 0 && (
          <div className="rounded-lg border border-warning/40 bg-warning/5 px-4 py-3 mb-4" data-testid="ai-workboard-attention">
            <div className="flex items-center gap-2 text-[13px] font-semibold text-warning mb-2">
              <AlertCircle className="h-4 w-4" /> Director attention ({attention.length})
            </div>
            <div className="space-y-1.5">
              {attention.map((a) => (
                <div key={a.id} data-testid={`ai-workboard-attention-${a.id}`} className="flex items-center justify-between gap-2 flex-wrap text-[13px]">
                  <span className="min-w-0 truncate">{a.title}</span>
                  <span className="rounded-full bg-warning/15 text-warning px-2 py-0.5 text-[11px] font-semibold uppercase">{a.attentionReason.replace(/_/g, " ")}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Workboard list */}
        {workboard.length === 0 ? (
          <p data-testid="ai-workboard-empty" className="text-muted-foreground text-[14px]">
            No workboard actions match the current filters.
          </p>
        ) : (
          <div className="space-y-3" data-testid="ai-workboard-list">
            {workboard.map((a) => (
              <WorkboardRow
                key={a.id}
                action={a}
                busy={busy}
                onAssign={handleAssign}
                onReassign={handleReassign}
                onBlock={handleBlock}
                onNote={handleNote}
                onVerb={handleWorkboardVerb}
              />
            ))}
          </div>
        )}
      </div>

      {/* Phase 16L — My Work Queue */}
      <div className="surface-elevated p-6 mt-6" data-testid="ai-my-work-section">
        <h3 className="font-display text-lg font-semibold flex items-center gap-2 mb-2">
          <UserCheck className="h-5 w-5 text-accent" /> My work queue
          {myPerms && (
            <span className="text-[11px] font-normal text-muted-foreground">
              ({myPerms.isAdmin ? "Director/Admin" : myPerms.departments.length
                ? `member: ${myPerms.departments.map((d) => d.department).join(", ")}`
                : "no department membership"})
            </span>
          )}
        </h3>
        <p
          data-testid="ai-my-work-safety-copy"
          className="text-[12px] text-muted-foreground mb-4"
        >
          Team members can only update internal workboard records they are assigned
          to or allowed to claim by department membership. These actions never send
          WhatsApp, create payment links, book shipments, call customers, invoke
          Vapi, or call a live AI provider.
        </p>

        {myWorkSummary && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5" data-testid="ai-my-work-summary">
            <SummaryCard label="My total" value={myWorkSummary.total} />
            <SummaryCard label="Assigned" value={myWorkSummary.assigned} />
            <SummaryCard label="In progress" value={myWorkSummary.inProgress} tone="accent" />
            <SummaryCard label="Blocked" value={myWorkSummary.blocked} tone={myWorkSummary.blocked ? "danger" : undefined} />
            <SummaryCard label="Due soon" value={myWorkSummary.dueSoon} tone={myWorkSummary.dueSoon ? "warning" : undefined} />
            <SummaryCard label="Overdue" value={myWorkSummary.overdue} tone={myWorkSummary.overdue ? "danger" : undefined} />
            <SummaryCard label="Completed" value={myWorkSummary.completedInternal} tone="success" />
          </div>
        )}

        {myWork.length === 0 ? (
          <p data-testid="ai-my-work-empty" className="text-muted-foreground text-[14px]">
            No work assigned to you yet. {myPerms && !myPerms.isAdmin && myPerms.departments.length === 0
              ? "Ask a Director/Admin to add you to a department."
              : "Claim eligible work from the Department action workboard above."}
          </p>
        ) : (
          <div className="space-y-3" data-testid="ai-my-work-list">
            {myWork.map((a) => (
              <MyWorkRow
                key={a.id}
                action={a}
                busy={busy}
                onBlock={handleBlock}
                onNote={handleNote}
                onVerb={handleWorkboardVerb}
              />
            ))}
          </div>
        )}
      </div>

      {/* Phase 16M — Workboard Analytics + SLA Throughput */}
      <div className="surface-elevated p-6 mt-6" data-testid="ai-workboard-analytics-section">
        <h3 className="font-display text-lg font-semibold flex items-center gap-2 mb-2">
          <BarChart3 className="h-5 w-5 text-accent" /> Workboard Analytics + SLA Throughput
        </h3>
        <p
          data-testid="ai-analytics-safety-copy"
          className="text-[12px] text-muted-foreground mb-4"
        >
          Read-only analytics only — this dashboard never sends WhatsApp, creates
          payment links, books shipments, calls customers, invokes Vapi, calls a
          live AI provider, changes work items, or mutates business data.
        </p>

        {!analytics ? (
          <p data-testid="ai-analytics-empty" className="text-muted-foreground text-[14px]">
            Analytics are unavailable right now. Please retry.
          </p>
        ) : (
          <>
            {/* Summary cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5" data-testid="ai-analytics-summary">
              <SummaryCard label="Open work" value={analytics.summary.openActions} />
              <SummaryCard label="Overdue" value={analytics.summary.overdue} tone={analytics.summary.overdue ? "danger" : undefined} />
              <SummaryCard label="Due soon" value={analytics.summary.dueSoon} tone={analytics.summary.dueSoon ? "warning" : undefined} />
              <SummaryCard label="Blocked" value={analytics.summary.blocked} tone={analytics.summary.blocked ? "danger" : undefined} />
              <SummaryCard label="Completed internal" value={analytics.summary.completedInternal} tone="success" />
              <Chip label="Avg completion" value={fmtHours(analytics.summary.avgCompletionHours)} tone="success" />
              <Chip label="Highest-risk dept" value={deptLabel(analytics, analytics.sla.highestRiskDepartment)} tone={analytics.sla.highestRiskDepartment ? "warning" : "success"} />
              <SummaryCard label="Director attention" value={analytics.summary.directorAttention} tone={analytics.summary.directorAttention ? "warning" : undefined} />
            </div>

            {/* Department workload table */}
            <div className="mb-5">
              <h4 className="text-[13px] font-semibold mb-2">Department workload</h4>
              {analytics.departments.length === 0 ? (
                <p data-testid="ai-analytics-dept-empty" className="text-[13px] text-muted-foreground">No department data yet.</p>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-border" data-testid="ai-analytics-dept-table">
                  <table className="w-full text-[13px] min-w-[640px]">
                    <thead className="bg-muted/40 text-muted-foreground">
                      <tr className="text-left">
                        <th className="px-3 py-2 font-medium">Department</th>
                        <th className="px-3 py-2 font-medium">Open</th>
                        <th className="px-3 py-2 font-medium">In progress</th>
                        <th className="px-3 py-2 font-medium">Blocked</th>
                        <th className="px-3 py-2 font-medium">Overdue</th>
                        <th className="px-3 py-2 font-medium">Due soon</th>
                        <th className="px-3 py-2 font-medium">Completed</th>
                        <th className="px-3 py-2 font-medium">Avg completion</th>
                      </tr>
                    </thead>
                    <tbody>
                      {analytics.departments.map((d) => (
                        <tr key={d.department || "unassigned"} data-testid={`ai-analytics-dept-${d.department || "unassigned"}`} className="border-t border-border">
                          <td className="px-3 py-2">{d.label || d.department || "Unassigned"}</td>
                          <td className="px-3 py-2">{d.open}</td>
                          <td className="px-3 py-2">{d.inProgress}</td>
                          <td className={`px-3 py-2 ${d.blocked ? "text-destructive" : ""}`}>{d.blocked}</td>
                          <td className={`px-3 py-2 ${d.overdue ? "text-destructive" : ""}`}>{d.overdue}</td>
                          <td className="px-3 py-2">{d.dueSoon}</td>
                          <td className="px-3 py-2 text-success">{d.completedInternal}</td>
                          <td className="px-3 py-2">{fmtHours(d.avgCompletionHours)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Member workload table */}
            <div className="mb-5">
              <h4 className="text-[13px] font-semibold mb-2">Member workload</h4>
              {analytics.members.length === 0 ? (
                <p data-testid="ai-analytics-member-empty" className="text-[13px] text-muted-foreground">No assigned members yet.</p>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-border" data-testid="ai-analytics-member-table">
                  <table className="w-full text-[13px] min-w-[560px]">
                    <thead className="bg-muted/40 text-muted-foreground">
                      <tr className="text-left">
                        <th className="px-3 py-2 font-medium">Member</th>
                        <th className="px-3 py-2 font-medium">Department</th>
                        <th className="px-3 py-2 font-medium">Assigned/open</th>
                        <th className="px-3 py-2 font-medium">In progress</th>
                        <th className="px-3 py-2 font-medium">Blocked</th>
                        <th className="px-3 py-2 font-medium">Overdue</th>
                        <th className="px-3 py-2 font-medium">Completed</th>
                      </tr>
                    </thead>
                    <tbody>
                      {analytics.members.map((m) => (
                        <tr key={m.userId} data-testid={`ai-analytics-member-${m.userId}`} className="border-t border-border">
                          <td className="px-3 py-2">{m.username ?? `#${m.userId}`}</td>
                          <td className="px-3 py-2 text-muted-foreground">{m.departments.join(", ") || "—"}</td>
                          <td className="px-3 py-2">{m.assignedOpen}</td>
                          <td className="px-3 py-2">{m.inProgress}</td>
                          <td className={`px-3 py-2 ${m.blocked ? "text-destructive" : ""}`}>{m.blocked}</td>
                          <td className={`px-3 py-2 ${m.overdue ? "text-destructive" : ""}`}>{m.overdue}</td>
                          <td className="px-3 py-2 text-success">{m.completedInternalRecent}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* SLA / blocker panel */}
            <div className="grid md:grid-cols-3 gap-3 mb-5" data-testid="ai-analytics-sla-panel">
              <div className="rounded-lg border border-border bg-muted/20 px-4 py-3">
                <div className="text-[12px] font-semibold mb-2 flex items-center gap-1.5"><AlertTriangle className="h-3.5 w-3.5 text-warning" /> Top blocker reasons</div>
                {analytics.blockers.topBlockerReasons.length === 0 ? (
                  <p className="text-[12px] text-muted-foreground">No blocked items.</p>
                ) : (
                  <ul className="space-y-1">
                    {analytics.blockers.topBlockerReasons.map((b, i) => (
                      <li key={i} className="flex items-center justify-between gap-2 text-[12px]">
                        <span className="min-w-0 truncate">{b.reason}</span>
                        <span className="rounded-full bg-destructive/15 text-destructive px-2 py-0.5 text-[11px] font-semibold">{b.count}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="rounded-lg border border-border bg-muted/20 px-4 py-3">
                <div className="text-[12px] font-semibold mb-2">Overdue by department</div>
                <DeptCountList analytics={analytics} map={analytics.sla.overdueByDepartment} tone="danger" />
              </div>
              <div className="rounded-lg border border-border bg-muted/20 px-4 py-3">
                <div className="text-[12px] font-semibold mb-2">Due soon by department</div>
                <DeptCountList analytics={analytics} map={analytics.sla.dueSoonByDepartment} tone="warning" />
              </div>
            </div>

            {/* Throughput trend */}
            <div data-testid="ai-analytics-trend">
              <h4 className="text-[13px] font-semibold mb-2">Throughput trend (last {analytics.trend.windowDays} days)</h4>
              {!analytics.trend.hasData ? (
                <p data-testid="ai-analytics-trend-empty" className="text-[13px] text-muted-foreground">
                  No throughput activity in this window yet ({analytics.trend.reason || "insufficient_event_data"}).
                </p>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-border">
                  <table className="w-full text-[13px] min-w-[560px]">
                    <thead className="bg-muted/40 text-muted-foreground">
                      <tr className="text-left">
                        <th className="px-3 py-2 font-medium">Date</th>
                        <th className="px-3 py-2 font-medium">Created</th>
                        <th className="px-3 py-2 font-medium">Assigned</th>
                        <th className="px-3 py-2 font-medium">Started</th>
                        <th className="px-3 py-2 font-medium">Blocked</th>
                        <th className="px-3 py-2 font-medium">Completed</th>
                      </tr>
                    </thead>
                    <tbody>
                      {analytics.trend.days.map((d) => (
                        <tr key={d.date} className="border-t border-border">
                          <td className="px-3 py-2 text-muted-foreground">{d.date}</td>
                          <td className="px-3 py-2">{d.created}</td>
                          <td className="px-3 py-2">{d.assigned}</td>
                          <td className="px-3 py-2">{d.started}</td>
                          <td className={`px-3 py-2 ${d.blocked ? "text-destructive" : ""}`}>{d.blocked}</td>
                          <td className="px-3 py-2 text-success">{d.completedInternal}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <p className="text-[11px] text-muted-foreground mt-4 flex items-center gap-1.5">
              <Lock className="h-3 w-3" /> read-only: {String(analytics.readonly)} · provider action taken: {String(analytics.providerActionTaken)} · external action taken: {String(analytics.externalActionTaken)}
            </p>
          </>
        )}
      </div>
    </div>
  );
}

function fmtHours(value: number | null): string {
  return value === null || value === undefined ? "—" : `${value}h`;
}

function deptLabel(analytics: AiWorkboardAnalytics, key: string): string {
  if (!key) return "None";
  const found = analytics.departments.find((d) => d.department === key);
  return found?.label || key.replace(/_/g, " ");
}

function DeptCountList({
  analytics,
  map,
  tone,
}: {
  analytics: AiWorkboardAnalytics;
  map: Record<string, number>;
  tone: "danger" | "warning";
}) {
  const entries = Object.entries(map);
  if (entries.length === 0) {
    return <p className="text-[12px] text-muted-foreground">None.</p>;
  }
  const badge = tone === "danger" ? "bg-destructive/15 text-destructive" : "bg-warning/15 text-warning";
  return (
    <ul className="space-y-1">
      {entries
        .sort((a, b) => b[1] - a[1])
        .map(([dept, count]) => (
          <li key={dept} className="flex items-center justify-between gap-2 text-[12px]">
            <span className="min-w-0 truncate">{dept === "unassigned" ? "Unassigned" : deptLabel(analytics, dept)}</span>
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${badge}`}>{count}</span>
          </li>
        ))}
    </ul>
  );
}

function MyWorkRow({
  action: a,
  busy,
  onBlock,
  onNote,
  onVerb,
}: {
  action: AiApprovedAction;
  busy: boolean;
  onBlock: (a: AiApprovedAction, reason: string) => void;
  onNote: (a: AiApprovedAction, note: string) => void;
  onVerb: (a: AiApprovedAction, verb: WorkboardVerb) => void;
}) {
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const p = a.permissions;
  const ws = a.workStatus ?? "unassigned";
  return (
    <div data-testid={`ai-my-work-item-${a.id}`} className="rounded-lg border border-border bg-muted/20 px-4 py-3">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <div className="font-medium">{a.title}</div>
          <div className="text-[12px] text-muted-foreground">
            {a.actionType.replace(/_/g, " ")} · {a.department || "no dept"} · {a.priority}
            {a.sourceSuggestionId ? ` · src #${a.sourceSuggestionId}` : ""}
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase ${WORK_STATUS_STYLES[ws] ?? WORK_STATUS_STYLES.unassigned}`}>
            {ws.replace(/_/g, " ")}
          </span>
          <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase ${SLA_STYLES[a.slaStatus ?? "no_due_date"]}`}>
            <Clock className="h-3 w-3" /> {(a.slaStatus ?? "no_due_date").replace(/_/g, " ")}
          </span>
        </div>
      </div>
      {a.blockerReason && <p className="text-[12px] text-destructive mt-1">Blocked: {a.blockerReason}</p>}

      <div className="flex flex-wrap items-center gap-1.5 mt-3">
        {p?.canStart && (
          <Button data-testid={`ai-my-work-start-${a.id}`} variant="outline" size="sm" disabled={busy} onClick={() => onVerb(a, "start")}>Start</Button>
        )}
        {p?.canBlock && (
          <>
            <Input data-testid={`ai-my-work-reason-${a.id}`} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Blocker reason" className="h-8 w-40" />
            <Button data-testid={`ai-my-work-block-${a.id}`} variant="outline" size="sm" disabled={busy} onClick={() => onBlock(a, reason)}>Block</Button>
          </>
        )}
        {p?.canUnblock && (
          <Button data-testid={`ai-my-work-unblock-${a.id}`} variant="outline" size="sm" disabled={busy} onClick={() => onVerb(a, "unblock")}>Unblock</Button>
        )}
        {p?.canCompleteInternal && (
          <Button data-testid={`ai-my-work-complete-${a.id}`} variant="outline" size="sm" disabled={busy} onClick={() => onVerb(a, "complete")}>
            <CheckCircle2 className="h-3.5 w-3.5 mr-1" /> Complete internal
          </Button>
        )}
        {p?.canAddNote && (
          <>
            <Input data-testid={`ai-my-work-note-input-${a.id}`} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add note" className="h-8 w-32" />
            <Button data-testid={`ai-my-work-note-${a.id}`} variant="outline" size="sm" disabled={busy} onClick={() => onNote(a, note)}>Add note</Button>
          </>
        )}
      </div>
      <p className="text-[11px] text-muted-foreground mt-2 flex items-center gap-1.5">
        <Lock className="h-3 w-3" /> external action taken: {String(a.externalActionTaken)} · provider action taken: {String(a.providerActionTaken)}
      </p>
    </div>
  );
}

function SummaryCard({ label, value, tone }: { label: string; value: number; tone?: "success" | "warning" | "danger" | "accent" }) {
  const toneClass =
    tone === "success" ? "text-success" : tone === "warning" ? "text-warning" : tone === "danger" ? "text-destructive" : tone === "accent" ? "text-accent" : "text-foreground";
  return (
    <div className="rounded-lg border border-border bg-muted/30 px-3 py-2">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={`text-[18px] font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}

function WorkboardRow({
  action: a,
  busy,
  onAssign,
  onReassign,
  onBlock,
  onNote,
  onVerb,
}: {
  action: AiApprovedAction;
  busy: boolean;
  onAssign: (a: AiApprovedAction, dept: string) => void;
  onReassign: (a: AiApprovedAction, dept: string) => void;
  onBlock: (a: AiApprovedAction, reason: string) => void;
  onNote: (a: AiApprovedAction, note: string) => void;
  onVerb: (a: AiApprovedAction, verb: WorkboardVerb) => void;
}) {
  const [dept, setDept] = useState("");
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const ws = a.workStatus ?? "unassigned";
  const terminal = ws === "completed_internal" || ws === "rejected" || ws === "cancelled";
  // Phase 16L — gate buttons by per-action permissions when present; when the
  // backend did not attach permissions (older payloads), fall back to showing all.
  const p = a.permissions;
  const allow = (key: keyof NonNullable<AiApprovedAction["permissions"]>): boolean =>
    !p || Boolean(p[key]);

  return (
    <div data-testid={`ai-workboard-item-${a.id}`} className="rounded-lg border border-border bg-muted/20 px-4 py-3">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <div className="font-medium">{a.title}</div>
          <div className="text-[12px] text-muted-foreground">
            {a.actionType.replace(/_/g, " ")} · {a.department || "no dept"} · {a.assigneeUser || "unassigned"} · {a.priority}
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase ${WORK_STATUS_STYLES[ws] ?? WORK_STATUS_STYLES.unassigned}`}>
            {ws.replace(/_/g, " ")}
          </span>
          <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase ${SLA_STYLES[a.slaStatus ?? "no_due_date"]}`}>
            <Clock className="h-3 w-3" /> {(a.slaStatus ?? "no_due_date").replace(/_/g, " ")}
          </span>
        </div>
      </div>

      {a.blockerReason && (
        <p className="text-[12px] text-destructive mt-1">Blocked: {a.blockerReason}</p>
      )}
      <p className="text-[11px] text-muted-foreground mt-1">
        Source suggestion #{a.sourceSuggestionId}
      </p>

      {!terminal && (
        <div className="flex flex-wrap items-center gap-1.5 mt-3">
          {ws === "unassigned" && allow("canAssign") && (
            <>
              <select aria-label="Assign department" data-testid={`ai-workboard-dept-${a.id}`} value={dept} onChange={(e) => setDept(e.target.value)} className="h-8 rounded-md border border-input bg-background px-2 text-[12px]">
                <option value="">Pick dept…</option>
                {DEPARTMENTS.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
              </select>
              <Button data-testid={`ai-workboard-assign-${a.id}`} variant="outline" size="sm" disabled={busy} onClick={() => onAssign(a, dept)}>Assign</Button>
            </>
          )}
          {ws === "unassigned" && allow("canClaim") && (
            <Button data-testid={`ai-workboard-claim-${a.id}`} variant="outline" size="sm" disabled={busy} onClick={() => onVerb(a, "claim")}>Claim</Button>
          )}
          {ws === "assigned" && allow("canStart") && (
            <Button data-testid={`ai-workboard-start-${a.id}`} variant="outline" size="sm" disabled={busy} onClick={() => onVerb(a, "start")}>Start</Button>
          )}
          {(ws === "assigned" || ws === "in_progress") && allow("canBlock") && (
            <>
              <Input data-testid={`ai-workboard-reason-${a.id}`} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Blocker reason" className="h-8 w-40" />
              <Button data-testid={`ai-workboard-block-${a.id}`} variant="outline" size="sm" disabled={busy} onClick={() => onBlock(a, reason)}>Block</Button>
            </>
          )}
          {ws === "blocked" && allow("canUnblock") && (
            <Button data-testid={`ai-workboard-unblock-${a.id}`} variant="outline" size="sm" disabled={busy} onClick={() => onVerb(a, "unblock")}>Unblock</Button>
          )}
          {(ws === "assigned" || ws === "in_progress" || ws === "blocked") && allow("canCompleteInternal") && (
            <Button data-testid={`ai-workboard-complete-${a.id}`} variant="outline" size="sm" disabled={busy} onClick={() => onVerb(a, "complete")}>
              <CheckCircle2 className="h-3.5 w-3.5 mr-1" /> Complete internal
            </Button>
          )}
          {allow("canReassign") && (
            <>
              <select aria-label="Reassign department" data-testid={`ai-workboard-reassign-dept-${a.id}`} value={dept} onChange={(e) => setDept(e.target.value)} className="h-8 rounded-md border border-input bg-background px-2 text-[12px]">
                <option value="">Reassign to…</option>
                {DEPARTMENTS.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
              </select>
              <Button data-testid={`ai-workboard-reassign-${a.id}`} variant="outline" size="sm" disabled={busy} onClick={() => onReassign(a, dept)}>Reassign</Button>
            </>
          )}
          {allow("canAddNote") && (
            <>
              <Input data-testid={`ai-workboard-note-input-${a.id}`} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add note" className="h-8 w-32" />
              <Button data-testid={`ai-workboard-note-${a.id}`} variant="outline" size="sm" disabled={busy} onClick={() => onNote(a, note)}>Add note</Button>
            </>
          )}
        </div>
      )}

      <p className="text-[11px] text-muted-foreground mt-2 flex items-center gap-1.5">
        <Lock className="h-3 w-3" /> external action taken: {String(a.externalActionTaken)} · provider action taken: {String(a.providerActionTaken)}
      </p>
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
