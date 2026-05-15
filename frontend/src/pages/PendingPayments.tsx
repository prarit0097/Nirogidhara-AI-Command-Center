import { useEffect, useMemo, useState } from "react";
import { api } from "@/services/api";
import type {
  PendingPaymentRow,
  PendingPaymentsDrilldownResponse,
} from "@/types/domain";

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

function formatAmount(amount: number): string {
  return `₹${amount.toLocaleString("en-IN")}`;
}

export default function PendingPaymentsPage() {
  const [data, setData] =
    useState<PendingPaymentsDrilldownResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [includePartial, setIncludePartial] = useState<boolean>(true);
  const [search, setSearch] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const response = await api.getPendingPaymentsDrilldown({
          includePartial,
        });
        if (!cancelled) setData(response);
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
  }, [includePartial]);

  const filtered = useMemo<PendingPaymentRow[]>(() => {
    if (!data) return [];
    const needle = search.trim().toLowerCase();
    if (!needle) return data.results;
    return data.results.filter((row) => {
      const fields = [
        row.customer_name,
        row.customer_phone,
        row.order_id,
        row.payment_id,
        row.order_state ?? "",
      ];
      return fields.some((field) =>
        field.toLowerCase().includes(needle),
      );
    });
  }, [data, search]);

  return (
    <div className="space-y-4" data-testid="pending-payments-page">
      <header className="space-y-1">
        <h1 className="font-display text-2xl font-semibold">
          Pending Payments — Director Action Review
        </h1>
        <p className="text-sm text-muted-foreground max-w-3xl">
          Read-only diagnostic. Surfaces every payment currently in{" "}
          <code>Pending</code> or <code>Partial</code> status, with order,
          customer, and last-communication context. <strong>No action
          buttons</strong> — sending a reminder or marking a payment is a
          separate approval-gated workflow (Phase 7E-Live-B). Sorted
          oldest first so the most stale records appear at the top.
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-3 surface-card px-4 py-3">
        <label
          className="flex items-center gap-2 text-sm"
          data-testid="pending-payments-include-partial-toggle"
        >
          <input
            type="checkbox"
            checked={includePartial}
            onChange={(e) => setIncludePartial(e.target.checked)}
          />
          <span>Include Partial</span>
        </label>
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter by customer name / phone / order / state"
          className="flex-1 min-w-[260px] rounded border border-border px-3 py-2 text-sm"
          data-testid="pending-payments-search"
        />
        {data && (
          <span className="text-xs text-muted-foreground">
            {filtered.length} of {data.count}
          </span>
        )}
      </div>

      {loading && (
        <div className="surface-card px-4 py-6 text-sm text-muted-foreground">
          Loading pending payments…
        </div>
      )}

      {error && (
        <div
          className="surface-card px-4 py-6 text-sm text-destructive"
          data-testid="pending-payments-error"
        >
          Failed to load: {error}
        </div>
      )}

      {!loading && !error && data && filtered.length === 0 && (
        <div
          className="surface-card px-4 py-8 text-sm text-muted-foreground text-center"
          data-testid="pending-payments-empty"
        >
          No pending payments match the current filters.
        </div>
      )}

      {!loading && !error && filtered.length > 0 && (
        <div className="surface-card overflow-x-auto">
          <table className="min-w-full text-left text-xs">
            <thead className="text-muted-foreground border-b border-border">
              <tr>
                <th className="px-4 py-3">Order</th>
                <th className="px-4 py-3">Customer</th>
                <th className="px-4 py-3">Phone</th>
                <th className="px-4 py-3">Amount</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">State</th>
                <th className="px-4 py-3">Days Pending</th>
                <th className="px-4 py-3">Last WhatsApp</th>
                <th className="px-4 py-3">Last Call</th>
                <th className="px-4 py-3">Last Call Outcome</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((row) => (
                <tr
                  key={row.payment_id}
                  data-testid="pending-payments-row"
                  className="border-b border-border last:border-0"
                >
                  <td className="px-4 py-2">{row.order_id}</td>
                  <td className="px-4 py-2">{row.customer_name}</td>
                  <td className="px-4 py-2">{row.customer_phone}</td>
                  <td className="px-4 py-2">{formatAmount(row.amount)}</td>
                  <td className="px-4 py-2">{row.payment_status}</td>
                  <td className="px-4 py-2">{row.order_state ?? "—"}</td>
                  <td className="px-4 py-2">{row.days_since_creation}</td>
                  <td className="px-4 py-2">
                    {formatDateTime(row.last_whatsapp_at)}
                  </td>
                  <td className="px-4 py-2">
                    {formatDateTime(row.last_call_at)}
                  </td>
                  <td className="px-4 py-2">
                    {row.last_call_outcome ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div
        className="surface-card bg-muted/20 px-4 py-3 text-xs text-muted-foreground"
        data-testid="pending-payments-read-only-banner"
      >
        <strong>Read-only diagnostic.</strong> No "Send Reminder" /
        "Mark Paid" / "Refund" / "Cancel" / "Trigger Call" buttons exist
        on this page. Action paths continue to require the existing
        approval-gated CLI workflows.
      </div>
    </div>
  );
}
