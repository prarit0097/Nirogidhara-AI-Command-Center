/**
 * Phase 15C - Audit Timeline page.
 *
 * Read-only standalone surface that lets admins / directors review
 * the Master Event Ledger across the whole system without touching
 * any other page or business state.
 *
 * Hard rules (matched by the backend AuditTimelineView):
 * - Read-only. There are no Send / Approve / Execute / Resume AI /
 *   Toggle Sandbox / Submit Rollback / Generate Briefing / Change
 *   Kill Switch buttons anywhere on this page.
 * - The backend sanitises every row; this page renders only what the
 *   backend returned. It never reads raw audit payloads.
 * - Filters are URL-safe; nothing on this page mutates state.
 */
import { useEffect, useMemo, useState } from "react";
import { api } from "@/services/api";
import type {
  AuditTimelineCategory,
  AuditTimelineFilters,
  AuditTimelineItem,
  AuditTimelineResponse,
  AuditTimelineTone,
} from "@/types/domain";

const CATEGORY_LABELS: Record<AuditTimelineCategory, string> = {
  safety: "Safety",
  rollback: "Rollback",
  ai_governance: "AI Governance",
  whatsapp: "WhatsApp",
  payments: "Payments",
  orders: "Orders",
  delivery: "Delivery",
  auth_system: "Auth / System",
  other: "Other",
};

const CATEGORY_CHIP_CLASS: Record<AuditTimelineCategory, string> = {
  safety: "bg-amber-100 text-amber-900 border-amber-200",
  rollback: "bg-orange-100 text-orange-900 border-orange-200",
  ai_governance: "bg-sky-100 text-sky-900 border-sky-200",
  whatsapp: "bg-emerald-100 text-emerald-900 border-emerald-200",
  payments: "bg-indigo-100 text-indigo-900 border-indigo-200",
  orders: "bg-purple-100 text-purple-900 border-purple-200",
  delivery: "bg-slate-100 text-slate-900 border-slate-200",
  auth_system: "bg-zinc-100 text-zinc-900 border-zinc-200",
  other: "bg-neutral-100 text-neutral-900 border-neutral-200",
};

const TONE_CHIP_CLASS: Record<AuditTimelineTone, string> = {
  success: "bg-green-100 text-green-900 border-green-200",
  info: "bg-blue-100 text-blue-900 border-blue-200",
  warning: "bg-amber-100 text-amber-900 border-amber-200",
  danger: "bg-rose-100 text-rose-900 border-rose-200",
};

const DEFAULT_LIMIT = 50;

function formatDateTime(value: string): string {
  if (!value) return "—";
  try {
    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) return value;
    return dt.toLocaleString();
  } catch {
    return value;
  }
}

function renderPayloadCell(payload: Record<string, unknown>): string {
  if (!payload || Object.keys(payload).length === 0) return "—";
  const pairs = Object.entries(payload)
    .slice(0, 6)
    .map(([key, value]) => {
      if (value === null || value === undefined) return `${key}=—`;
      if (typeof value === "object") {
        try {
          return `${key}=${JSON.stringify(value).slice(0, 60)}`;
        } catch {
          return `${key}=[object]`;
        }
      }
      const text = String(value);
      return `${key}=${text.length > 60 ? text.slice(0, 60) + "..." : text}`;
    });
  return pairs.join(" · ");
}

export default function AuditTimelinePage() {
  const [data, setData] = useState<AuditTimelineResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Filter state — none of these mutate any business row.
  const [filters, setFilters] = useState<AuditTimelineFilters>({
    kind: "",
    tone: "",
    category: "",
    q: "",
    dateFrom: "",
    dateTo: "",
    limit: DEFAULT_LIMIT,
    offset: 0,
  });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const response = await api.getAuditTimeline({
          kind: filters.kind || undefined,
          tone: (filters.tone || undefined) as
            | AuditTimelineTone
            | undefined,
          category: (filters.category || undefined) as
            | AuditTimelineCategory
            | undefined,
          q: filters.q || undefined,
          dateFrom: filters.dateFrom || undefined,
          dateTo: filters.dateTo || undefined,
          limit: filters.limit,
          offset: filters.offset,
        });
        if (!cancelled) setData(response);
      } catch (err: unknown) {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : "Failed to load audit timeline.",
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
  }, [
    filters.kind,
    filters.tone,
    filters.category,
    filters.q,
    filters.dateFrom,
    filters.dateTo,
    filters.limit,
    filters.offset,
  ]);

  const categories = useMemo<AuditTimelineCategory[]>(() => {
    return (
      data?.categoriesAvailable ?? [
        "safety",
        "rollback",
        "ai_governance",
        "whatsapp",
        "payments",
        "orders",
        "delivery",
        "auth_system",
        "other",
      ]
    );
  }, [data]);

  const pageStart = data ? data.offset + 1 : 0;
  const pageEnd = data
    ? Math.min(data.offset + data.items.length, data.count)
    : 0;
  const hasPrev = data ? data.offset > 0 : false;
  const hasNext = data
    ? data.offset + data.items.length < data.count
    : false;

  function patchFilters(patch: Partial<AuditTimelineFilters>): void {
    setFilters((prev) => ({
      ...prev,
      ...patch,
      // Any filter change resets pagination so users never see a
      // stale page-2 view from a previous filter set.
      offset: patch.offset != null ? patch.offset : 0,
    }));
  }

  return (
    <div className="p-6 space-y-6" data-testid="audit-timeline-page">
      {/* Header */}
      <header className="space-y-1">
        <h1 className="text-2xl font-display font-semibold">
          Audit Timeline
        </h1>
        <p className="text-sm text-foreground/65">
          Read-only window into the Master Event Ledger. Sanitised
          server-side — secrets, full phone numbers, customer PII,
          prompt bodies, and provider payloads are never returned.
          Nothing on this page mutates state.
        </p>
      </header>

      {/* Filter bar */}
      <section
        className="rounded-2xl border border-border bg-background p-4 space-y-3"
        data-testid="audit-timeline-filters"
      >
        <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <label className="text-xs font-medium space-y-1">
            <span className="block text-foreground/70">Kind (exact)</span>
            <input
              type="text"
              placeholder="e.g. payment.received"
              value={filters.kind ?? ""}
              onChange={(e) => patchFilters({ kind: e.target.value })}
              className="w-full rounded-md border border-input bg-background px-2 py-1 text-sm"
              data-testid="audit-filter-kind"
            />
          </label>
          <label className="text-xs font-medium space-y-1">
            <span className="block text-foreground/70">Tone</span>
            <select
              value={filters.tone ?? ""}
              onChange={(e) =>
                patchFilters({ tone: e.target.value as AuditTimelineTone | "" })
              }
              className="w-full rounded-md border border-input bg-background px-2 py-1 text-sm"
              data-testid="audit-filter-tone"
            >
              <option value="">All tones</option>
              <option value="success">success</option>
              <option value="info">info</option>
              <option value="warning">warning</option>
              <option value="danger">danger</option>
            </select>
          </label>
          <label className="text-xs font-medium space-y-1">
            <span className="block text-foreground/70">Category</span>
            <select
              value={filters.category ?? ""}
              onChange={(e) =>
                patchFilters({
                  category: e.target.value as AuditTimelineCategory | "",
                })
              }
              className="w-full rounded-md border border-input bg-background px-2 py-1 text-sm"
              data-testid="audit-filter-category"
            >
              <option value="">All categories</option>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {CATEGORY_LABELS[c]}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs font-medium space-y-1">
            <span className="block text-foreground/70">Search text</span>
            <input
              type="search"
              placeholder="substring match"
              value={filters.q ?? ""}
              onChange={(e) => patchFilters({ q: e.target.value })}
              className="w-full rounded-md border border-input bg-background px-2 py-1 text-sm"
              data-testid="audit-filter-q"
            />
          </label>
          <label className="text-xs font-medium space-y-1">
            <span className="block text-foreground/70">From (UTC)</span>
            <input
              type="datetime-local"
              value={filters.dateFrom ?? ""}
              onChange={(e) => patchFilters({ dateFrom: e.target.value })}
              className="w-full rounded-md border border-input bg-background px-2 py-1 text-sm"
              data-testid="audit-filter-date-from"
            />
          </label>
          <label className="text-xs font-medium space-y-1">
            <span className="block text-foreground/70">To (UTC)</span>
            <input
              type="datetime-local"
              value={filters.dateTo ?? ""}
              onChange={(e) => patchFilters({ dateTo: e.target.value })}
              className="w-full rounded-md border border-input bg-background px-2 py-1 text-sm"
              data-testid="audit-filter-date-to"
            />
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs text-foreground/60">
          <button
            type="button"
            onClick={() =>
              setFilters({
                kind: "",
                tone: "",
                category: "",
                q: "",
                dateFrom: "",
                dateTo: "",
                limit: DEFAULT_LIMIT,
                offset: 0,
              })
            }
            className="rounded-md border border-input bg-background px-3 py-1 hover:bg-accent"
            data-testid="audit-filter-clear"
          >
            Clear filters
          </button>
          <span data-testid="audit-timeline-meta">
            {data
              ? `Showing ${pageStart}–${pageEnd} of ${data.count}`
              : "Loading…"}
          </span>
        </div>
      </section>

      {/* States: loading / error / empty / table */}
      {loading && (
        <div
          className="rounded-2xl border border-border bg-background p-6 text-sm text-foreground/60"
          data-testid="audit-timeline-loading"
        >
          Loading audit events…
        </div>
      )}
      {!loading && error && (
        <div
          className="rounded-2xl border border-rose-300 bg-rose-50 p-6 text-sm text-rose-900"
          data-testid="audit-timeline-error"
        >
          {error}
        </div>
      )}
      {!loading && !error && data && data.items.length === 0 && (
        <div
          className="rounded-2xl border border-border bg-background p-6 text-sm text-foreground/60"
          data-testid="audit-timeline-empty"
        >
          No audit events match the current filters.
        </div>
      )}

      {!loading && !error && data && data.items.length > 0 && (
        <section
          className="rounded-2xl border border-border bg-background overflow-hidden"
          data-testid="audit-timeline-table"
        >
          <table className="w-full text-left text-sm">
            <thead className="bg-muted/40 text-xs uppercase tracking-wider text-foreground/55">
              <tr>
                <th className="px-3 py-2">When (local)</th>
                <th className="px-3 py-2">Category</th>
                <th className="px-3 py-2">Kind</th>
                <th className="px-3 py-2">Tone</th>
                <th className="px-3 py-2">Text</th>
                <th className="px-3 py-2">Sanitised payload</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((item: AuditTimelineItem) => (
                <tr
                  key={item.id}
                  className="border-t border-border"
                  data-testid={`audit-row-${item.id}`}
                  data-category={item.category}
                  data-tone={item.tone}
                  data-kind={item.kind}
                >
                  <td className="px-3 py-2 whitespace-nowrap text-foreground/80">
                    {formatDateTime(item.occurredAt)}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`inline-block rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${CATEGORY_CHIP_CLASS[item.category]}`}
                    >
                      {CATEGORY_LABELS[item.category]}
                    </span>
                  </td>
                  <td className="px-3 py-2 font-mono text-[12px]">
                    {item.kind}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`inline-block rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${TONE_CHIP_CLASS[item.tone]}`}
                    >
                      {item.tone}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-foreground/85">
                    {item.text}
                  </td>
                  <td className="px-3 py-2 font-mono text-[11px] text-foreground/65">
                    {renderPayloadCell(item.payload)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {/* Pagination footer */}
      {!loading && !error && data && (data.count > data.items.length || data.offset > 0) && (
        <div
          className="flex items-center justify-end gap-3 text-xs text-foreground/60"
          data-testid="audit-timeline-pagination"
        >
          <button
            type="button"
            disabled={!hasPrev}
            onClick={() =>
              setFilters((prev) => ({
                ...prev,
                offset: Math.max((prev.offset ?? 0) - (prev.limit ?? DEFAULT_LIMIT), 0),
              }))
            }
            className="rounded-md border border-input bg-background px-3 py-1 disabled:opacity-50 hover:bg-accent"
            data-testid="audit-timeline-prev"
          >
            Previous
          </button>
          <button
            type="button"
            disabled={!hasNext}
            onClick={() =>
              setFilters((prev) => ({
                ...prev,
                offset: (prev.offset ?? 0) + (prev.limit ?? DEFAULT_LIMIT),
              }))
            }
            className="rounded-md border border-input bg-background px-3 py-1 disabled:opacity-50 hover:bg-accent"
            data-testid="audit-timeline-next"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
