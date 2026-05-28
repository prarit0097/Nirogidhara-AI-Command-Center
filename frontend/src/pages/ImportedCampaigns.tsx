import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { api, isApiError } from "@/services/api";
import type {
  ImportedCallOutcome,
  ImportedCampaign,
  ImportedQueueItem,
} from "@/types/domain";
import { AlertTriangle, Megaphone, Phone, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

const OUTCOME_OPTIONS: { value: ImportedCallOutcome; label: string }[] = [
  { value: "interested", label: "Interested" },
  { value: "not_interested", label: "Not interested" },
  { value: "callback", label: "Callback" },
  { value: "wrong_number", label: "Wrong number" },
  { value: "no_answer", label: "No answer" },
  { value: "already_ordered", label: "Already ordered" },
  { value: "angry_escalation", label: "Angry → senior review" },
  { value: "medical_emergency", label: "Medical emergency → escalate" },
];

export default function ImportedCampaigns() {
  const [campaigns, setCampaigns] = useState<ImportedCampaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [queue, setQueue] = useState<ImportedQueueItem[]>([]);
  const [queueLoading, setQueueLoading] = useState(false);
  const [drafts, setDrafts] = useState<Record<number, ImportedCallOutcome>>({});
  const [busyId, setBusyId] = useState<number | null>(null);

  const loadCampaigns = () => {
    setLoading(true);
    api
      .getImportCampaigns()
      .then((r) => {
        setCampaigns(r.items);
        if (r.items.length > 0) {
          // Functional update avoids reading `selectedId` here (keeps this
          // loader dependency-free) while only auto-selecting when unset.
          setSelectedId((cur) => cur ?? r.items[0].id);
        }
      })
      .catch(() => setCampaigns([]))
      .finally(() => setLoading(false));
  };

  const loadQueue = (campaignId: number) => {
    setQueueLoading(true);
    api
      .getImportCampaignQueue(campaignId)
      .then((r) => {
        setQueue(r.items);
        const initial: Record<number, ImportedCallOutcome> = {};
        for (const q of r.items) initial[q.id] = "interested";
        setDrafts(initial);
      })
      .catch(() => setQueue([]))
      .finally(() => setQueueLoading(false));
  };

  useEffect(loadCampaigns, []);
  useEffect(() => {
    if (selectedId !== null) loadQueue(selectedId);
  }, [selectedId]);

  const handleOutcome = async (item: ImportedQueueItem) => {
    const outcome = drafts[item.id];
    if (!outcome) return;
    setBusyId(item.id);
    try {
      await api.recordImportOutcome(item.id, { outcome });
      toast.success(`Outcome recorded: ${outcome.replace(/_/g, " ")}.`);
      if (selectedId !== null) loadQueue(selectedId);
      loadCampaigns();
    } catch (err) {
      if (isApiError(err)) {
        toast.error(`Could not record outcome (HTTP ${err.httpStatus}).`);
      } else {
        toast.error("Could not record outcome. Please retry.");
      }
    } finally {
      setBusyId(null);
    }
  };

  const handleCreateOrder = async (item: ImportedQueueItem) => {
    setBusyId(item.id);
    try {
      const res = await api.createImportOrder(item.id, {});
      toast.success(`Internal order ${res.orderId} created (${res.orderStage}).`);
      if (selectedId !== null) loadQueue(selectedId);
      loadCampaigns();
    } catch (err) {
      if (isApiError(err)) {
        toast.error(`Could not create order (HTTP ${err.httpStatus}).`);
      } else {
        toast.error("Could not create order. Please retry.");
      }
    } finally {
      setBusyId(null);
    }
  };

  const selected = campaigns.find((c) => c.id === selectedId) ?? null;

  return (
    <div data-testid="imported-campaigns-page">
      <PageHeader
        eyebrow="Operations"
        title="Imported Campaigns"
        description="Run the calling lifecycle on uploaded customer data: record outcomes, escalate, and create internal orders for interested contacts."
      />

      <div className="mb-6 flex items-start gap-2 rounded-xl border border-border bg-muted/40 px-4 py-3 text-[13px] text-muted-foreground">
        <ShieldCheck className="h-4 w-4 mt-0.5 shrink-0 text-success" />
        <span>
          Internal workflow only — recording an outcome or creating an order
          never sends WhatsApp, takes a payment, books a courier, or places a
          Vapi/AI call. Order creation uses the existing internal order flow.
        </span>
      </div>

      {loading ? (
        <div className="h-48 grid place-items-center text-muted-foreground">
          Loading campaigns…
        </div>
      ) : campaigns.length === 0 ? (
        <div
          data-testid="imported-campaigns-empty"
          className="surface-elevated p-6 text-muted-foreground text-[14px]"
        >
          No imported campaigns yet. Upload a dataset on the Data Imports page
          and create a campaign from its valid rows.
        </div>
      ) : (
        <>
          {/* Campaign list */}
          <div className="surface-elevated p-6 mb-6">
            <h2 className="font-display text-lg font-semibold flex items-center gap-2 mb-4">
              <Megaphone className="h-5 w-5 text-accent" /> Campaigns ({campaigns.length})
            </h2>
            <div className="overflow-x-auto">
              <table data-testid="imported-campaigns-table" className="w-full text-[13.5px] border-collapse">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wider text-muted-foreground border-b border-border">
                    <th className="py-2 pr-3">Name</th>
                    <th className="py-2 pr-3">Problem</th>
                    <th className="py-2 pr-3">Status</th>
                    <th className="py-2 pr-3">Contacts</th>
                    <th className="py-2 pr-3">Pending</th>
                    <th className="py-2 pr-3">Interested</th>
                    <th className="py-2 pr-3">Orders</th>
                    <th className="py-2 pr-3"></th>
                  </tr>
                </thead>
                <tbody>
                  {campaigns.map((c) => (
                    <tr
                      key={c.id}
                      className={`border-b border-border/60 last:border-0 ${
                        c.id === selectedId ? "bg-accent/5" : ""
                      }`}
                    >
                      <td className="py-2 pr-3 font-medium">{c.name}</td>
                      <td className="py-2 pr-3">{c.problemCategory || "—"}</td>
                      <td className="py-2 pr-3 capitalize">{c.status}</td>
                      <td className="py-2 pr-3 tabular-nums">{c.totalContacts}</td>
                      <td className="py-2 pr-3 tabular-nums">{c.pendingCount}</td>
                      <td className="py-2 pr-3 tabular-nums text-success">{c.interestedCount}</td>
                      <td className="py-2 pr-3 tabular-nums">{c.orderCreatedCount}</td>
                      <td className="py-2 pr-3">
                        <Button
                          size="sm"
                          variant={c.id === selectedId ? "default" : "outline"}
                          data-testid={`imported-campaign-open-${c.id}`}
                          onClick={() => setSelectedId(c.id)}
                        >
                          {c.id === selectedId ? "Viewing" : "Open queue"}
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Queue for the selected campaign */}
          {selected && (
            <div className="surface-elevated p-6">
              <h2 className="font-display text-lg font-semibold flex items-center gap-2 mb-4">
                <Phone className="h-5 w-5 text-accent" /> Call queue — {selected.name}
              </h2>
              {queueLoading ? (
                <p className="text-muted-foreground text-[14px]">Loading queue…</p>
              ) : queue.length === 0 ? (
                <p data-testid="imported-queue-empty" className="text-muted-foreground text-[14px]">
                  No contacts in this campaign's queue.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table data-testid="imported-queue-table" className="w-full text-[13.5px] border-collapse">
                    <thead>
                      <tr className="text-left text-[11px] uppercase tracking-wider text-muted-foreground border-b border-border">
                        <th className="py-2 pr-3">S.N.</th>
                        <th className="py-2 pr-3">Contact</th>
                        <th className="py-2 pr-3">Phone</th>
                        <th className="py-2 pr-3">Status</th>
                        <th className="py-2 pr-3">Attempts</th>
                        <th className="py-2 pr-3">Outcome</th>
                        <th className="py-2 pr-3"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {queue.map((q, idx) => (
                        <tr key={q.id} className="border-b border-border/60 last:border-0 align-top">
                          <td className="py-2 pr-3 text-muted-foreground">{idx + 1}</td>
                          <td className="py-2 pr-3">
                            <div className="font-medium">{q.name || "—"}</div>
                            <div className="text-[12px] text-muted-foreground">
                              {q.problemCategory || ""}
                              {q.escalationFlag && (
                                <span className="ml-1 inline-flex items-center gap-1 text-destructive">
                                  <AlertTriangle className="h-3 w-3" />
                                  {q.escalationFlag === "medical_emergency"
                                    ? "Medical emergency"
                                    : "Senior review"}
                                </span>
                              )}
                            </div>
                          </td>
                          <td className="py-2 pr-3 font-mono text-[12px]">{q.phoneMasked}</td>
                          <td className="py-2 pr-3 capitalize">{q.status.replace(/_/g, " ")}</td>
                          <td className="py-2 pr-3 tabular-nums">{q.callAttempts}</td>
                          <td className="py-2 pr-3">
                            <select
                              data-testid={`imported-queue-outcome-${q.id}`}
                              aria-label={`Outcome for ${q.name}`}
                              value={drafts[q.id] ?? "interested"}
                              onChange={(e) =>
                                setDrafts((d) => ({
                                  ...d,
                                  [q.id]: e.target.value as ImportedCallOutcome,
                                }))
                              }
                              className="h-9 rounded-md border border-input bg-background px-2 text-[13px]"
                            >
                              {OUTCOME_OPTIONS.map((o) => (
                                <option key={o.value} value={o.value}>
                                  {o.label}
                                </option>
                              ))}
                            </select>
                          </td>
                          <td className="py-2 pr-3 space-x-2 whitespace-nowrap">
                            <Button
                              size="sm"
                              variant="outline"
                              data-testid={`imported-queue-save-${q.id}`}
                              disabled={busyId === q.id || q.status === "order_created"}
                              onClick={() => handleOutcome(q)}
                            >
                              {busyId === q.id ? "Saving…" : "Record"}
                            </Button>
                            {q.status === "interested" && !q.linkedOrderId && (
                              <Button
                                size="sm"
                                data-testid={`imported-queue-create-order-${q.id}`}
                                disabled={busyId === q.id}
                                onClick={() => handleCreateOrder(q)}
                              >
                                Create order
                              </Button>
                            )}
                            {q.linkedOrderId && (
                              <span className="text-[12px] text-success">
                                {q.linkedOrderId}
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
