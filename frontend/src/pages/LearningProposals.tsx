import { useEffect, useMemo, useState } from "react";
import { api } from "@/services/api";
import type {
  LearningProposal,
  LearningProposalStatus,
  LearningProposalSummary,
  LearningProposalsListResponse,
} from "@/types/domain";

type StatusTab = "all" | LearningProposalStatus;

const STATUS_TABS: { value: StatusTab; label: string }[] = [
  { value: "all", label: "All" },
  { value: "pending", label: "Pending" },
  { value: "approved", label: "Approved" },
  { value: "implemented", label: "Implemented" },
  { value: "rejected", label: "Rejected" },
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

function impactClass(scope: string): string {
  if (scope === "high") {
    return "rounded-full bg-red-100 text-red-800 px-2 py-0.5 text-[10px]";
  }
  if (scope === "medium") {
    return "rounded-full bg-amber-100 text-amber-800 px-2 py-0.5 text-[10px]";
  }
  return "rounded-full bg-muted/40 px-2 py-0.5 text-[10px]";
}

function statusClass(status: string): string {
  if (status === "pending") {
    return "rounded-full bg-amber-100 text-amber-800 px-2 py-0.5 text-[10px]";
  }
  if (status === "approved") {
    return "rounded-full bg-blue-100 text-blue-800 px-2 py-0.5 text-[10px]";
  }
  if (status === "implemented") {
    return "rounded-full bg-green-100 text-green-800 px-2 py-0.5 text-[10px]";
  }
  if (status === "rejected") {
    return "rounded-full bg-red-100 text-red-800 px-2 py-0.5 text-[10px]";
  }
  if (status === "cancelled") {
    return "rounded-full bg-muted/40 px-2 py-0.5 text-[10px]";
  }
  return "rounded-full bg-muted/40 px-2 py-0.5 text-[10px]";
}

export default function LearningProposalsPage() {
  const [data, setData] =
    useState<LearningProposalsListResponse | null>(null);
  const [summary, setSummary] =
    useState<LearningProposalSummary | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [statusTab, setStatusTab] = useState<StatusTab>("pending");
  const [search, setSearch] = useState<string>("");
  const [expandedId, setExpandedId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [list, summ] = await Promise.all([
          api.getLearningProposals(
            statusTab === "all"
              ? { limit: 100 }
              : { status: statusTab, limit: 100 },
          ),
          api.getLearningProposalSummary(),
        ]);
        if (!cancelled) {
          setData(list);
          setSummary(summ);
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
  }, [statusTab]);

  const filtered = useMemo<LearningProposal[]>(() => {
    if (!data) return [];
    const needle = search.trim().toLowerCase();
    if (!needle) return data.results;
    return data.results.filter((row) =>
      [row.title, row.proposal_type, row.source_agent]
        .filter(Boolean)
        .some((field) => field.toLowerCase().includes(needle)),
    );
  }, [data, search]);

  return (
    <div
      className="space-y-4"
      data-testid="learning-proposals-page"
    >
      <header className="space-y-1">
        <h1 className="font-display text-2xl font-semibold">
          Learning Proposals — Director Review Queue
        </h1>
        <p className="text-sm text-muted-foreground max-w-3xl">
          CAIO creates proposals from governance findings. Director
          approves/implements via CLI. <strong>Read-only diagnostic</strong>{" "}
          — use the CLI commands below to act on proposals.
        </p>
      </header>

      <div
        className="surface-card px-4 py-3 text-xs"
        data-testid="learning-proposals-cli-reference"
      >
        <p className="text-muted-foreground mb-2">
          <strong>CLI commands (Director only):</strong>
        </p>
        <pre className="rounded bg-muted/30 p-3 overflow-x-auto text-[11px] whitespace-pre-wrap">
{`python manage.py list_learning_proposals
python manage.py review_learning_proposal <id> --decision approved --operator-name NAME
python manage.py implement_learning_proposal <id> --implementation-note "..."`}
        </pre>
      </div>

      {summary && (
        <div
          className="surface-card grid gap-2 px-4 py-3 sm:grid-cols-2 lg:grid-cols-6 text-xs"
          data-testid="learning-proposals-summary-tiles"
        >
          <div className="rounded border border-border px-3 py-2">
            <div className="text-muted-foreground">Pending</div>
            <div className="text-lg font-semibold">{summary.pending}</div>
          </div>
          <div className="rounded border border-border px-3 py-2">
            <div className="text-muted-foreground">Approved</div>
            <div className="text-lg font-semibold">{summary.approved}</div>
          </div>
          <div className="rounded border border-border px-3 py-2">
            <div className="text-muted-foreground">Implemented</div>
            <div className="text-lg font-semibold">
              {summary.implemented}
            </div>
          </div>
          <div className="rounded border border-border px-3 py-2">
            <div className="text-muted-foreground">Rejected</div>
            <div className="text-lg font-semibold">{summary.rejected}</div>
          </div>
          <div className="rounded border border-border px-3 py-2">
            <div className="text-muted-foreground">Cancelled</div>
            <div className="text-lg font-semibold">
              {summary.cancelled}
            </div>
          </div>
          <div className="rounded border border-border px-3 py-2">
            <div className="text-muted-foreground">High-impact pending</div>
            <div className="text-lg font-semibold">
              {summary.high_impact_pending}
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 surface-card px-4 py-3">
        <div
          className="flex flex-wrap gap-1"
          data-testid="learning-proposals-status-tabs"
        >
          {STATUS_TABS.map((tab) => (
            <button
              key={tab.value}
              type="button"
              onClick={() => setStatusTab(tab.value)}
              className={
                statusTab === tab.value
                  ? "rounded-full bg-primary text-primary-foreground px-3 py-1 text-xs"
                  : "rounded-full border border-border px-3 py-1 text-xs"
              }
              data-testid={`learning-proposals-tab-${tab.value}`}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter by title / type / source"
          className="flex-1 min-w-[260px] rounded border border-border px-3 py-2 text-sm"
          data-testid="learning-proposals-search"
        />
        {data && (
          <span className="text-xs text-muted-foreground">
            {filtered.length} of {data.count}
          </span>
        )}
      </div>

      {loading && (
        <div className="surface-card px-4 py-6 text-sm text-muted-foreground">
          Loading proposals…
        </div>
      )}

      {error && (
        <div
          className="surface-card px-4 py-6 text-sm text-destructive"
          data-testid="learning-proposals-error"
        >
          Failed to load: {error}
        </div>
      )}

      {!loading && !error && filtered.length === 0 && (
        <div
          className="surface-card px-4 py-8 text-sm text-muted-foreground text-center"
          data-testid="learning-proposals-empty"
        >
          No proposals found.
        </div>
      )}

      {!loading && !error && filtered.length > 0 && (
        <div className="surface-card overflow-x-auto">
          <table className="min-w-full text-left text-xs">
            <thead className="text-muted-foreground border-b border-border">
              <tr>
                <th className="px-4 py-3">ID</th>
                <th className="px-4 py-3">Title</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Scope</th>
                <th className="px-4 py-3">Source</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Created</th>
                <th className="px-4 py-3">Reviewed By</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((row) => {
                const expanded = expandedId === row.id;
                return (
                  <>
                    <tr
                      key={row.id}
                      data-testid="learning-proposal-row"
                      className="border-b border-border last:border-0 cursor-pointer hover:bg-muted/20"
                      onClick={() =>
                        setExpandedId(expanded ? null : row.id)
                      }
                    >
                      <td className="px-4 py-2">#{row.id}</td>
                      <td className="px-4 py-2">{row.title}</td>
                      <td className="px-4 py-2">{row.proposal_type}</td>
                      <td className="px-4 py-2">
                        <span className={impactClass(row.impact_scope)}>
                          {row.impact_scope}
                        </span>
                      </td>
                      <td className="px-4 py-2">{row.source_agent}</td>
                      <td className="px-4 py-2">
                        <span className={statusClass(row.status)}>
                          {row.status}
                        </span>
                      </td>
                      <td className="px-4 py-2">
                        {formatDateTime(row.created_at)}
                      </td>
                      <td className="px-4 py-2">
                        {row.reviewed_by || "—"}
                      </td>
                    </tr>
                    {expanded && (
                      <tr
                        key={`${row.id}-expanded`}
                        data-testid="learning-proposal-expanded"
                        className="border-b border-border last:border-0 bg-muted/10"
                      >
                        <td colSpan={8} className="px-4 py-3">
                          <div className="space-y-3 text-xs">
                            <div>
                              <p className="font-medium mb-1">
                                Proposed change (internal-only)
                              </p>
                              <p className="text-muted-foreground whitespace-pre-line">
                                {row.proposed_change_text}
                              </p>
                            </div>
                            <div>
                              <p className="font-medium mb-1">Evidence</p>
                              <pre className="rounded bg-muted/30 p-3 overflow-x-auto text-[11px] whitespace-pre-wrap">
                                {JSON.stringify(row.evidence, null, 2)}
                              </pre>
                            </div>
                            {row.director_note && (
                              <div>
                                <p className="font-medium mb-1">
                                  Director note
                                </p>
                                <p className="text-muted-foreground italic">
                                  {row.director_note}
                                </p>
                              </div>
                            )}
                            {row.implementation_note && (
                              <div>
                                <p className="font-medium mb-1">
                                  Implementation note
                                </p>
                                <p className="text-muted-foreground italic">
                                  {row.implementation_note}
                                </p>
                                <p className="text-muted-foreground mt-1">
                                  Implemented by {row.implemented_by}{" "}
                                  on {formatDateTime(row.implemented_at)}.
                                </p>
                              </div>
                            )}
                            {row.caio_snapshot_id !== null && (
                              <div className="text-muted-foreground">
                                Linked CAIO snapshot:{" "}
                                <code className="rounded bg-muted/30 px-1">
                                  #{row.caio_snapshot_id}
                                </code>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div
        className="surface-card bg-muted/20 px-4 py-3 text-xs text-muted-foreground"
        data-testid="learning-proposals-read-only-banner"
      >
        <strong>Read-only diagnostic.</strong> No "Approve" /
        "Reject" / "Implement" buttons exist on this page. All
        Phase 11D state transitions are CLI-only (see commands
        above). Phase 11D NEVER auto-modifies any prompt or live
        configuration — Director manually implements every approved
        change.
      </div>
    </div>
  );
}
