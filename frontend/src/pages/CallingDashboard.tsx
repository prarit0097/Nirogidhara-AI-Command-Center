import { useEffect, useMemo, useState } from "react";
import { api } from "@/services/api";
import type {
  AiCallCampaignGate,
  AiCallCampaignGateStatus,
  AiCallCampaignGatesListResponse,
  CallOutcomeDetected,
  CallOutcomeRecord,
  CallOutcomeRecordsListResponse,
  CallOutcomeRecordsSummary,
  CallOutcomeReviewStatus,
  PostCallFollowUp,
  PostCallFollowUpListResponse,
  PostCallFollowUpStatus,
  PostCallFollowUpSummary,
} from "@/types/domain";

type OutcomeStatusTab = "all" | CallOutcomeReviewStatus;
type FollowUpStatusTab = "all" | PostCallFollowUpStatus;

const OUTCOME_TABS: { value: OutcomeStatusTab; label: string }[] = [
  { value: "all", label: "All" },
  { value: "pending", label: "Pending Review" },
  { value: "approved", label: "Approved" },
  { value: "applied", label: "Applied" },
  { value: "skipped", label: "Skipped" },
];

const FOLLOWUP_TABS: { value: FollowUpStatusTab; label: string }[] = [
  { value: "all", label: "All" },
  { value: "pending", label: "Pending" },
  { value: "gate_prepared", label: "Gate Prepared" },
  { value: "dispatched", label: "Dispatched" },
];

function formatDateTime(value: string | null): string {
  if (!value) return "—";
  try {
    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) return value;
    return dt.toLocaleString();
  } catch {
    return value;
  }
}

function campaignStatusClass(status: AiCallCampaignGateStatus): string {
  switch (status) {
    case "completed":
      return "rounded-full bg-green-100 text-green-800 px-2 py-0.5 text-[10px]";
    case "executing":
      return "rounded-full bg-amber-100 text-amber-800 px-2 py-0.5 text-[10px]";
    case "approved":
      return "rounded-full bg-blue-100 text-blue-800 px-2 py-0.5 text-[10px]";
    case "failed":
      return "rounded-full bg-red-100 text-red-800 px-2 py-0.5 text-[10px]";
    case "draft":
    case "cancelled":
    default:
      return "rounded-full bg-muted/40 px-2 py-0.5 text-[10px]";
  }
}

function outcomeClass(detected: CallOutcomeDetected): string {
  switch (detected) {
    case "connected_converted":
      return "rounded-full bg-green-100 text-green-800 px-2 py-0.5 text-[10px]";
    case "connected_callback":
      return "rounded-full bg-amber-100 text-amber-800 px-2 py-0.5 text-[10px]";
    case "connected_not_interested":
      return "rounded-full bg-red-100 text-red-800 px-2 py-0.5 text-[10px]";
    case "connected_unclear":
    case "not_connected":
    case "no_transcript":
    default:
      return "rounded-full bg-muted/40 px-2 py-0.5 text-[10px]";
  }
}

function confidenceClass(level: string): string {
  if (level === "high") {
    return "rounded-full bg-green-100 text-green-800 px-2 py-0.5 text-[10px]";
  }
  if (level === "medium") {
    return "rounded-full bg-amber-100 text-amber-800 px-2 py-0.5 text-[10px]";
  }
  return "rounded-full bg-muted/40 px-2 py-0.5 text-[10px]";
}

function reviewStatusClass(status: string): string {
  switch (status) {
    case "applied":
      return "rounded-full bg-green-100 text-green-800 px-2 py-0.5 text-[10px]";
    case "approved":
      return "rounded-full bg-blue-100 text-blue-800 px-2 py-0.5 text-[10px]";
    case "skipped":
      return "rounded-full bg-muted/40 px-2 py-0.5 text-[10px]";
    case "pending":
    default:
      return "rounded-full bg-amber-100 text-amber-800 px-2 py-0.5 text-[10px]";
  }
}

function followUpStatusClass(status: PostCallFollowUpStatus): string {
  switch (status) {
    case "dispatched":
      return "rounded-full bg-green-100 text-green-800 px-2 py-0.5 text-[10px]";
    case "gate_prepared":
      return "rounded-full bg-blue-100 text-blue-800 px-2 py-0.5 text-[10px]";
    case "pending":
      return "rounded-full bg-amber-100 text-amber-800 px-2 py-0.5 text-[10px]";
    case "needs_customer_setup":
      return "rounded-full bg-orange-100 text-orange-800 px-2 py-0.5 text-[10px]";
    case "gate_prep_failed":
      return "rounded-full bg-red-100 text-red-800 px-2 py-0.5 text-[10px]";
    case "skipped":
    case "sandbox_skipped":
    default:
      return "rounded-full bg-muted/40 px-2 py-0.5 text-[10px]";
  }
}

export default function CallingDashboardPage() {
  // Section 1 — campaigns.
  const [campaigns, setCampaigns] =
    useState<AiCallCampaignGatesListResponse | null>(null);

  // Section 2 — outcomes.
  const [outcomesSummary, setOutcomesSummary] =
    useState<CallOutcomeRecordsSummary | null>(null);
  const [outcomes, setOutcomes] =
    useState<CallOutcomeRecordsListResponse | null>(null);
  const [outcomeTab, setOutcomeTab] = useState<OutcomeStatusTab>("all");
  const [outcomeSearch, setOutcomeSearch] = useState<string>("");

  // Section 3 — follow-ups.
  const [followUpSummary, setFollowUpSummary] =
    useState<PostCallFollowUpSummary | null>(null);
  const [followUps, setFollowUps] =
    useState<PostCallFollowUpListResponse | null>(null);
  const [followUpTab, setFollowUpTab] = useState<FollowUpStatusTab>("all");

  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [
          campaignsResp,
          outcomesSummaryResp,
          outcomesResp,
          followUpSummaryResp,
          followUpsResp,
        ] = await Promise.all([
          api.getCallingCampaigns({ limit: 25 }),
          api.getCallOutcomesSummary(),
          api.getCallOutcomes(
            outcomeTab === "all"
              ? { limit: 100 }
              : { status: outcomeTab, limit: 100 },
          ),
          api.getPostCallFollowUpSummary(),
          api.getPostCallFollowUps(
            followUpTab === "all"
              ? { limit: 100 }
              : { status: followUpTab, limit: 100 },
          ),
        ]);
        if (!cancelled) {
          setCampaigns(campaignsResp);
          setOutcomesSummary(outcomesSummaryResp);
          setOutcomes(outcomesResp);
          setFollowUpSummary(followUpSummaryResp);
          setFollowUps(followUpsResp);
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : "Failed to load",
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [outcomeTab, followUpTab]);

  const filteredOutcomes = useMemo<CallOutcomeRecord[]>(() => {
    if (!outcomes) return [];
    const needle = outcomeSearch.trim().toLowerCase();
    if (!needle) return outcomes.results;
    return outcomes.results.filter((row) =>
      [row.callId, row.leadId]
        .filter(Boolean)
        .some((f) => f.toLowerCase().includes(needle)),
    );
  }, [outcomes, outcomeSearch]);

  const campaignRows: AiCallCampaignGate[] = campaigns?.results || [];
  const outcomeBy = outcomesSummary?.byOutcome || {};
  const followUpBy = followUpSummary?.byStatus || {};

  return (
    <div
      className="space-y-6"
      data-testid="calling-dashboard-page"
    >
      <header className="space-y-1">
        <h1 className="font-display text-2xl font-semibold">
          Tier-4 AI Calling — Performance Dashboard
        </h1>
        <p className="text-sm text-muted-foreground">
          Gate-approved Vapi calling campaigns with deterministic
          outcome classification and queued WhatsApp follow-ups. All
          state changes happen via CLI — this dashboard is read-only.
        </p>
      </header>

      <div
        className="rounded-md border border-border bg-amber-50 text-amber-900 px-4 py-2 text-xs"
        data-testid="calling-dashboard-banner"
      >
        <strong>Read-only.</strong> No "Run Campaign" / "Send
        WhatsApp" / "Approve" / "Apply" buttons exist on this page.
        Use the CLI commands in the reference section below.
      </div>

      {loading && (
        <div className="text-sm text-muted-foreground">Loading…</div>
      )}
      {error && (
        <div className="text-sm text-red-700">{error}</div>
      )}

      {/* ------- Section 1 — Campaign History ------- */}
      <section
        className="surface-card overflow-hidden"
        data-testid="calling-dashboard-campaigns-section"
      >
        <div className="border-b border-border px-6 py-4">
          <h2 className="font-display text-lg font-semibold">
            Campaign History
          </h2>
          <p className="text-xs text-muted-foreground mt-1">
            Phase 12A AI Calling Campaign Gates. Latest 25.
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted/20 text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-4 py-2">ID</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Stage filter</th>
                <th className="px-4 py-2">Leads</th>
                <th className="px-4 py-2">Dispatched</th>
                <th className="px-4 py-2">Skipped</th>
                <th className="px-4 py-2">Assistant</th>
                <th className="px-4 py-2">Vapi mode</th>
                <th className="px-4 py-2">Operator</th>
                <th className="px-4 py-2">Prepared</th>
              </tr>
            </thead>
            <tbody>
              {campaignRows.length === 0 ? (
                <tr>
                  <td
                    colSpan={10}
                    className="px-4 py-6 text-center text-xs text-muted-foreground"
                    data-testid="calling-dashboard-campaigns-empty"
                  >
                    No campaigns yet. Use Phase 12A CLI to prepare a
                    campaign.
                  </td>
                </tr>
              ) : (
                campaignRows.map((c) => (
                  <tr
                    key={c.id}
                    className="border-t border-border"
                    data-testid="calling-dashboard-campaign-row"
                  >
                    <td className="px-4 py-2 font-mono">#{c.id}</td>
                    <td className="px-4 py-2">
                      <span className={campaignStatusClass(c.status)}>
                        {c.status}
                      </span>
                      {c.sandbox && (
                        <span className="ml-1 rounded-full bg-amber-100 text-amber-800 px-2 py-0.5 text-[10px]">
                          sandbox
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-xs">
                      {(c.stageFilter || []).join(", ") || "—"}
                    </td>
                    <td className="px-4 py-2 font-mono text-xs">
                      {c.leadsSelectedCount}
                    </td>
                    <td className="px-4 py-2 font-mono text-xs">
                      {c.callsDispatched}
                    </td>
                    <td className="px-4 py-2 font-mono text-xs">
                      {c.callsSkipped}
                    </td>
                    <td className="px-4 py-2 font-mono text-xs">
                      {c.aiAssistantIdLast4 || "—"}
                    </td>
                    <td className="px-4 py-2 text-xs">
                      {c.vapiModeAtExecute || "—"}
                    </td>
                    <td className="px-4 py-2 text-xs">
                      {c.operatorName || "—"}
                    </td>
                    <td className="px-4 py-2 text-xs">
                      {formatDateTime(c.preparedAt)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* ------- Section 2 — Call Outcomes ------- */}
      <section
        className="surface-card overflow-hidden"
        data-testid="calling-dashboard-outcomes-section"
      >
        <div className="border-b border-border px-6 py-4">
          <h2 className="font-display text-lg font-semibold">
            Call Outcomes
          </h2>
          <p className="text-xs text-muted-foreground mt-1">
            Phase 12B deterministic classifier output. Director
            reviews + approves + applies via CLI.
          </p>
        </div>
        <div className="px-6 py-4 space-y-4">
          {/* Summary tiles */}
          {outcomesSummary && (
            <div
              className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3"
              data-testid="calling-dashboard-outcomes-summary"
            >
              <SummaryTile
                label="Total"
                value={outcomesSummary.total}
              />
              <SummaryTile
                label="Converted"
                value={outcomeBy.connected_converted || 0}
                tone="green"
              />
              <SummaryTile
                label="Callback"
                value={outcomeBy.connected_callback || 0}
                tone="amber"
              />
              <SummaryTile
                label="Not interested"
                value={outcomeBy.connected_not_interested || 0}
                tone="red"
              />
              <SummaryTile
                label="Not connected"
                value={outcomeBy.not_connected || 0}
              />
              <SummaryTile
                label="No transcript"
                value={outcomeBy.no_transcript || 0}
              />
            </div>
          )}

          {/* Status tabs + search */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex flex-wrap gap-1">
              {OUTCOME_TABS.map((t) => (
                <button
                  key={t.value}
                  type="button"
                  onClick={() => setOutcomeTab(t.value)}
                  className={
                    outcomeTab === t.value
                      ? "rounded-md bg-primary px-3 py-1 text-xs text-primary-foreground"
                      : "rounded-md border border-border px-3 py-1 text-xs hover:bg-muted/30"
                  }
                  data-testid={`outcome-tab-${t.value}`}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <input
              type="text"
              placeholder="Search by lead_id or call_id"
              value={outcomeSearch}
              onChange={(e) => setOutcomeSearch(e.target.value)}
              className="ml-auto rounded-md border border-border bg-background px-3 py-1 text-xs w-64"
              data-testid="outcome-search"
            />
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/20 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-4 py-2">Call ID</th>
                  <th className="px-4 py-2">Lead ID</th>
                  <th className="px-4 py-2">Outcome</th>
                  <th className="px-4 py-2">Confidence</th>
                  <th className="px-4 py-2">Suggested</th>
                  <th className="px-4 py-2">Review</th>
                  <th className="px-4 py-2">Classified</th>
                </tr>
              </thead>
              <tbody>
                {filteredOutcomes.length === 0 ? (
                  <tr>
                    <td
                      colSpan={7}
                      className="px-4 py-6 text-center text-xs text-muted-foreground"
                    >
                      No matching outcomes.
                    </td>
                  </tr>
                ) : (
                  filteredOutcomes.map((row) => (
                    <tr
                      key={row.id}
                      className="border-t border-border"
                      data-testid="calling-dashboard-outcome-row"
                    >
                      <td className="px-4 py-2 font-mono text-xs">
                        {row.callId}
                      </td>
                      <td className="px-4 py-2 font-mono text-xs">
                        {row.leadId}
                      </td>
                      <td className="px-4 py-2">
                        <span className={outcomeClass(row.detectedOutcome)}>
                          {row.detectedOutcome}
                        </span>
                      </td>
                      <td className="px-4 py-2">
                        <span className={confidenceClass(row.confidence)}>
                          {row.confidence}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-xs">
                        {row.suggestedLeadStatus || "—"}
                      </td>
                      <td className="px-4 py-2">
                        <span className={reviewStatusClass(row.reviewStatus)}>
                          {row.reviewStatus}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-xs">
                        {formatDateTime(row.classifiedAt)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* ------- Section 3 — WhatsApp Follow-up Queue ------- */}
      <section
        className="surface-card overflow-hidden"
        data-testid="calling-dashboard-followups-section"
      >
        <div className="border-b border-border px-6 py-4">
          <h2 className="font-display text-lg font-semibold">
            WhatsApp Follow-up Queue
          </h2>
          <p className="text-xs text-muted-foreground mt-1">
            Phase 12C queues follow-up suggestions. The actual
            WhatsApp send is the Director's separate Phase 7E-Live-B
            approve + execute step — NEVER auto-sent.
          </p>
        </div>
        <div className="px-6 py-4 space-y-4">
          {followUpSummary && (
            <div
              className="grid grid-cols-2 sm:grid-cols-4 gap-3"
              data-testid="calling-dashboard-followup-summary"
            >
              <SummaryTile
                label="Pending"
                value={followUpBy.pending || 0}
                tone="amber"
              />
              <SummaryTile
                label="Gate prepared"
                value={followUpBy.gate_prepared || 0}
                tone="blue"
              />
              <SummaryTile
                label="Dispatched"
                value={followUpBy.dispatched || 0}
                tone="green"
              />
              <SummaryTile
                label="Needs setup"
                value={followUpBy.needs_customer_setup || 0}
                tone="orange"
              />
            </div>
          )}

          <div className="flex flex-wrap gap-1">
            {FOLLOWUP_TABS.map((t) => (
              <button
                key={t.value}
                type="button"
                onClick={() => setFollowUpTab(t.value)}
                className={
                  followUpTab === t.value
                    ? "rounded-md bg-primary px-3 py-1 text-xs text-primary-foreground"
                    : "rounded-md border border-border px-3 py-1 text-xs hover:bg-muted/30"
                }
                data-testid={`followup-tab-${t.value}`}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/20 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-4 py-2">ID</th>
                  <th className="px-4 py-2">Lead ID</th>
                  <th className="px-4 py-2">Phone (last 4)</th>
                  <th className="px-4 py-2">Type</th>
                  <th className="px-4 py-2">Status</th>
                  <th className="px-4 py-2">Customer</th>
                  <th className="px-4 py-2">Phase 7E gate</th>
                  <th className="px-4 py-2">Created</th>
                </tr>
              </thead>
              <tbody>
                {!followUps || followUps.results.length === 0 ? (
                  <tr>
                    <td
                      colSpan={8}
                      className="px-4 py-6 text-center text-xs text-muted-foreground"
                    >
                      No follow-ups in this view.
                    </td>
                  </tr>
                ) : (
                  followUps.results.map((row: PostCallFollowUp) => (
                    <tr
                      key={row.id}
                      className="border-t border-border"
                      data-testid="calling-dashboard-followup-row"
                    >
                      <td className="px-4 py-2 font-mono text-xs">
                        #{row.id}
                      </td>
                      <td className="px-4 py-2 font-mono text-xs">
                        {row.leadId}
                      </td>
                      <td className="px-4 py-2 font-mono text-xs">
                        ***{row.phoneLast4}
                      </td>
                      <td className="px-4 py-2 text-xs">
                        {row.followUpType}
                      </td>
                      <td className="px-4 py-2">
                        <span className={followUpStatusClass(row.status)}>
                          {row.status}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-xs">
                        {row.customerFound ? "yes" : "no"}
                      </td>
                      <td className="px-4 py-2 font-mono text-xs">
                        {row.phase7eGateId ?? "—"}
                      </td>
                      <td className="px-4 py-2 text-xs">
                        {formatDateTime(row.createdAt)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* ------- Section 4 — CLI Reference ------- */}
      <section
        className="surface-card overflow-hidden"
        data-testid="calling-dashboard-cli-section"
      >
        <div className="border-b border-border px-6 py-4">
          <h2 className="font-display text-lg font-semibold">
            CLI Reference
          </h2>
          <p className="text-xs text-muted-foreground mt-1">
            Director-triggered management commands. All state changes
            happen via these — no UI buttons.
          </p>
        </div>
        <div className="px-6 py-4 space-y-4 text-xs">
          <CliBlock
            title="Phase 12A — Call a batch of leads"
            lines={[
              "python manage.py prepare_ai_calling_campaign --stage Interested --max-leads 10",
              "python manage.py approve_ai_calling_campaign <id> --operator-name 'Prarit' --intent '...' \\",
              "    --director-signoff 'BEGIN_UTC=...Z END_UTC=...Z'",
              "AI_CALLING_ENABLED=true python manage.py execute_ai_calling_campaign <id> \\",
              "    --operator-name 'Prarit' --confirm-ai-calling-campaign",
            ]}
          />
          <CliBlock
            title="Phase 12B — Classify call outcomes"
            lines={[
              "python manage.py classify_call_outcomes --campaign-id <id>",
              "python manage.py review_call_outcomes",
              "python manage.py approve_call_outcome <record_id> --operator-name 'Prarit'",
              "python manage.py apply_call_outcome_updates --operator-name 'Prarit' --confirm-outcome-apply",
            ]}
          />
          <CliBlock
            title="Phase 12C — Queue WhatsApp follow-ups"
            lines={[
              "python manage.py list_post_call_followups --status pending",
              "python manage.py prepare_post_call_followup_gate <id> --operator-name 'Prarit'",
              "python manage.py mark_followup_dispatched <id> --operator-name 'Prarit'",
              "python manage.py skip_post_call_followup <id> --operator-name 'Prarit' --reason '...'",
            ]}
          />
        </div>
      </section>
    </div>
  );
}

function SummaryTile({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: number;
  tone?: "default" | "green" | "amber" | "red" | "blue" | "orange";
}) {
  const toneClass =
    tone === "green"
      ? "border-green-200 bg-green-50"
      : tone === "amber"
        ? "border-amber-200 bg-amber-50"
        : tone === "red"
          ? "border-red-200 bg-red-50"
          : tone === "blue"
            ? "border-blue-200 bg-blue-50"
            : tone === "orange"
              ? "border-orange-200 bg-orange-50"
              : "border-border bg-muted/10";
  return (
    <div
      className={`rounded-md border px-3 py-2 ${toneClass}`}
      data-testid={`summary-tile-${label.toLowerCase().replace(/\s+/g, "-")}`}
    >
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="text-lg font-semibold font-mono">{value}</div>
    </div>
  );
}

function CliBlock({
  title,
  lines,
}: {
  title: string;
  lines: string[];
}) {
  return (
    <div>
      <div className="font-medium mb-1">{title}</div>
      <pre className="rounded-md border border-border bg-muted/20 px-3 py-2 overflow-x-auto text-[11px] leading-relaxed">
        {lines.join("\n")}
      </pre>
    </div>
  );
}
