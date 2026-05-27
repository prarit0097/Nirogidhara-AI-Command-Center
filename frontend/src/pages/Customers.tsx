import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { api } from "@/services/api";
import type {
  CustomerTimelineResponse,
  WhatsAppCustomerTimeline,
  WhatsAppInternalNote,
  WhatsAppMessage,
} from "@/types/domain";
import {
  AlertTriangle,
  CheckCheck,
  CreditCard,
  Globe,
  Heart,
  MapPin,
  MessageSquare,
  Phone,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Star,
  Truck,
} from "lucide-react";

export default function Customers() {
  const [customers, setCustomers] = useState<any[]>([]);
  const [active, setActive] = useState<any | null>(null);
  const [waTimeline, setWaTimeline] = useState<WhatsAppCustomerTimeline | null>(
    null,
  );
  const [waLoading, setWaLoading] = useState(false);
  // Phase 16B — Customer 360 unified timeline (calls/orders/payments/shipments).
  const [timeline, setTimeline] = useState<CustomerTimelineResponse | null>(null);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [timelineError, setTimelineError] = useState<string | null>(null);

  useEffect(() => { api.getCustomers().then((c) => { setCustomers(c); setActive(c[0]); }); }, []);

  useEffect(() => {
    if (!active?.id) {
      setWaTimeline(null);
      return;
    }
    setWaLoading(true);
    api
      .getCustomerWhatsAppTimeline(active.id)
      .then((data) => setWaTimeline(data))
      .finally(() => setWaLoading(false));
  }, [active?.id]);

  // Phase 16B — hydrate Calls / Orders / Payments / Delivery tabs.
  useEffect(() => {
    if (!active?.id) {
      setTimeline(null);
      setTimelineError(null);
      return;
    }
    let cancelled = false;
    setTimelineLoading(true);
    setTimelineError(null);
    api
      .getCustomerTimeline(active.id)
      .then((data) => {
        if (!cancelled) setTimeline(data);
      })
      .catch((err) => {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : "Could not load timeline";
          setTimelineError(msg.slice(0, 160));
        }
      })
      .finally(() => {
        if (!cancelled) setTimelineLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [active?.id]);

  if (!active) return <div className="h-96 grid place-items-center text-muted-foreground">Loading…</div>;

  return (
    <>
      <PageHeader eyebrow="Sales" title="Customer 360" description="Complete customer profile — calls, orders, payments, delivery, consent and reorder potential." />

      <div className="grid lg:grid-cols-[300px_1fr] gap-6">
        {/* Customer list */}
        <div className="surface-card p-3 max-h-[700px] overflow-auto scrollbar-thin">
          {customers.map((c) => (
            <button key={c.id} onClick={() => setActive(c)} className={`w-full text-left p-3 rounded-xl mb-1 transition ${active.id === c.id ? "bg-gradient-emerald-soft border border-primary/20" : "hover:bg-muted/60"}`}>
              <div className="flex items-center gap-2.5">
                <div className="h-9 w-9 rounded-full bg-gradient-hero text-primary-foreground grid place-items-center text-xs font-semibold">
                  {c.name.split(" ").map((n: string) => n[0]).slice(0, 2).join("")}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium truncate">{c.name}</div>
                  <div className="text-[11px] text-muted-foreground truncate">{c.productInterest}</div>
                </div>
              </div>
            </button>
          ))}
        </div>

        {/* Profile */}
        <div className="space-y-6">
          <div className="surface-elevated p-6 relative overflow-hidden">
            <div className="absolute -right-10 -top-10 h-40 w-40 rounded-full bg-gradient-gold opacity-10 blur-2xl" />
            <div className="flex flex-col md:flex-row md:items-start gap-4 md:gap-6 relative">
              <div className="h-16 w-16 rounded-2xl bg-gradient-hero text-primary-foreground grid place-items-center text-xl font-semibold shadow-elevated shrink-0">
                {active.name.split(" ").map((n: string) => n[0]).slice(0, 2).join("")}
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-display text-2xl font-semibold">{active.name}</div>
                <div className="text-sm text-muted-foreground">{active.id} · {active.diseaseCategory}</div>
                <div className="flex flex-wrap gap-3 mt-3 text-sm text-muted-foreground">
                  <span className="inline-flex items-center gap-1.5"><Phone className="h-3.5 w-3.5" />{active.phone}</span>
                  <span className="inline-flex items-center gap-1.5"><MapPin className="h-3.5 w-3.5" />{active.city}, {active.state}</span>
                  <span className="inline-flex items-center gap-1.5"><Globe className="h-3.5 w-3.5" />{active.language}</span>
                </div>
                <div className="flex flex-wrap gap-2 mt-3">
                  <StatusPill tone="info">Interest: {active.productInterest}</StatusPill>
                  <StatusPill tone="accent">Reorder: {active.reorderProbability}%</StatusPill>
                  <StatusPill tone="success">CSAT {active.satisfaction}/5</StatusPill>
                  {active.riskFlags.length > 0 && <StatusPill tone="warning" icon={<AlertTriangle className="h-3 w-3" />}>{active.riskFlags[0]}</StatusPill>}
                </div>
              </div>
              <div className="flex flex-col gap-2">
                <Button size="sm" className="bg-gradient-hero text-primary-foreground"><Phone className="h-3.5 w-3.5 mr-1" />Call</Button>
                <Button size="sm" variant="outline"><MessageSquare className="h-3.5 w-3.5 mr-1" />WhatsApp</Button>
              </div>
            </div>
          </div>

          <div className="grid lg:grid-cols-[1fr_340px] gap-6">
            <Tabs defaultValue="overview">
              <TabsList className="bg-muted/60">
                <TabsTrigger value="overview">Overview</TabsTrigger>
                <TabsTrigger value="calls">Calls</TabsTrigger>
                <TabsTrigger value="orders">Orders</TabsTrigger>
                <TabsTrigger value="payments">Payments</TabsTrigger>
                <TabsTrigger value="delivery">Delivery</TabsTrigger>
                <TabsTrigger value="whatsapp">WhatsApp</TabsTrigger>
                <TabsTrigger value="consent">Consent</TabsTrigger>
                <TabsTrigger value="reorder">Reorder</TabsTrigger>
              </TabsList>

              <TabsContent value="overview" className="surface-card p-6 mt-3">
                <h3 className="font-display text-lg font-semibold mb-2">AI Summary</h3>
                <p className="text-sm text-muted-foreground leading-relaxed">{active.aiSummary}</p>
                <div className="grid sm:grid-cols-2 gap-4 mt-5">
                  <div>
                    <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1.5">Lifestyle notes</div>
                    <div className="text-sm">{active.lifestyleNotes}</div>
                  </div>
                  <div>
                    <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1.5">Objections</div>
                    <div className="flex flex-wrap gap-1.5">
                      {active.objections.map((o: string) => <StatusPill key={o} tone="warning">{o}</StatusPill>)}
                    </div>
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="calls" className="surface-card p-6 mt-3">
                <CallsTab loading={timelineLoading} error={timelineError} timeline={timeline} />
              </TabsContent>

              <TabsContent value="orders" className="surface-card p-6 mt-3">
                <OrdersTab loading={timelineLoading} error={timelineError} timeline={timeline} />
              </TabsContent>
              <TabsContent value="payments" className="surface-card p-6 mt-3">
                <PaymentsTab loading={timelineLoading} error={timelineError} timeline={timeline} />
              </TabsContent>
              <TabsContent value="delivery" className="surface-card p-6 mt-3">
                <DeliveryTab loading={timelineLoading} error={timelineError} timeline={timeline} />
              </TabsContent>
              <TabsContent value="whatsapp" className="surface-card p-6 mt-3">
                <WhatsAppTab timeline={waTimeline} loading={waLoading} />
              </TabsContent>
              <TabsContent value="consent" className="surface-card p-6 mt-3">
                <h3 className="font-display text-lg font-semibold mb-3">Consent & privacy</h3>
                <ul className="space-y-2 text-sm">
                  {Object.entries(active.consent).map(([k, v]) => (
                    <li key={k} className="flex items-center justify-between rounded-lg bg-muted/40 px-3 py-2">
                      <span className="capitalize">{k}</span>
                      <StatusPill tone={v ? "success" : "neutral"} icon={<ShieldCheck className="h-3 w-3" />}>{v ? "Granted" : "Not granted"}</StatusPill>
                    </li>
                  ))}
                </ul>
              </TabsContent>
              <TabsContent value="reorder" className="surface-card p-6 mt-3"><EmptyTab icon={RefreshCw} text="Reorder nudges & success follow-ups." /></TabsContent>
            </Tabs>

            <div className="space-y-4">
              <div className="surface-card p-5">
                <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1">Reorder probability</div>
                <div className="font-display text-3xl font-semibold">{active.reorderProbability}%</div>
                <div className="h-2 rounded-full bg-muted mt-2 overflow-hidden">
                  <div className="h-full bg-gradient-gold rounded-full" style={{ width: `${active.reorderProbability}%` }} />
                </div>
              </div>
              <div className="surface-card p-5">
                <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">Satisfaction</div>
                <div className="flex">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Star key={i} className={`h-5 w-5 ${i < active.satisfaction ? "fill-accent text-accent" : "text-muted"}`} />
                  ))}
                </div>
              </div>
              <div className="surface-card p-5">
                <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">Family / referrals</div>
                <div className="text-sm text-muted-foreground"><Heart className="h-4 w-4 inline mr-1.5 text-destructive" />Linked relationships will appear here.</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

// Phase 16B — Customer 360 tab hydration. Each sub-tab consumes the
// unified `getCustomerTimeline` payload (calls / orders / payments /
// shipments) and renders compact tables. Loading + error + empty states
// are handled per-tab.

interface TimelineTabProps {
  loading: boolean;
  error: string | null;
  timeline: CustomerTimelineResponse | null;
}

function timelineHeader(label: string) {
  return <h3 className="font-display text-lg font-semibold mb-3">{label}</h3>;
}

function timelineStatusBanner(loading: boolean, error: string | null) {
  if (loading) {
    return (
      <div className="text-sm text-muted-foreground py-2" data-testid="customer-timeline-loading">
        Loading…
      </div>
    );
  }
  if (error) {
    return (
      <div
        className="rounded-lg bg-destructive/10 border border-destructive/20 text-destructive p-2.5 text-xs mb-3"
        data-testid="customer-timeline-error"
      >
        {error}
      </div>
    );
  }
  return null;
}

function CallsTab({ loading, error, timeline }: TimelineTabProps) {
  return (
    <>
      {timelineHeader("Call timeline")}
      {timelineStatusBanner(loading, error)}
      {!loading && !error && (timeline?.calls?.length ?? 0) === 0 && (
        <EmptyTab icon={Phone} text="No call history for this customer yet." />
      )}
      {timeline && timeline.calls.length > 0 && (
        <ol
          className="relative border-l border-border ml-3 space-y-5"
          data-testid="customer-calls-list"
        >
          {timeline.calls.map((c) => (
            <li key={c.id} className="ml-4">
              <span className="absolute -left-[7px] mt-1.5 h-3 w-3 rounded-full bg-primary ring-4 ring-background" />
              <div className="text-xs text-muted-foreground">
                {c.createdAt} · {c.agent || "—"} ·{" "}
                <StatusPill tone="info">{c.status}</StatusPill>
              </div>
              <div className="text-sm">
                {c.duration && <span className="text-muted-foreground">[{c.duration}] </span>}
                {c.summary || "No summary captured."}
              </div>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}

function OrdersTab({ loading, error, timeline }: TimelineTabProps) {
  return (
    <>
      {timelineHeader("Order history")}
      {timelineStatusBanner(loading, error)}
      {!loading && !error && (timeline?.orders?.length ?? 0) === 0 && (
        <EmptyTab icon={CreditCard} text="No orders for this customer yet." />
      )}
      {timeline && timeline.orders.length > 0 && (
        <div className="overflow-x-auto" data-testid="customer-orders-list">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left font-medium px-3 py-2">Order</th>
                <th className="text-left font-medium py-2">Product</th>
                <th className="text-left font-medium py-2">Stage</th>
                <th className="text-right font-medium px-3 py-2">Amount</th>
              </tr>
            </thead>
            <tbody>
              {timeline.orders.map((o) => (
                <tr key={o.id} className="border-t border-border/60">
                  <td className="px-3 py-2 font-mono text-xs">{o.id}</td>
                  <td className="py-2">{o.product || "—"}</td>
                  <td className="py-2"><StatusPill tone="info">{o.stage}</StatusPill></td>
                  <td className="px-3 py-2 text-right font-semibold tabular-nums">₹{o.amount?.toLocaleString?.() ?? o.amount}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function PaymentsTab({ loading, error, timeline }: TimelineTabProps) {
  return (
    <>
      {timelineHeader("Payments")}
      {timelineStatusBanner(loading, error)}
      {!loading && !error && (timeline?.payments?.length ?? 0) === 0 && (
        <EmptyTab icon={CreditCard} text="No payment records for this customer yet." />
      )}
      {timeline && timeline.payments.length > 0 && (
        <div className="overflow-x-auto" data-testid="customer-payments-list">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left font-medium px-3 py-2">Payment</th>
                <th className="text-left font-medium py-2">Order</th>
                <th className="text-left font-medium py-2">Status</th>
                <th className="text-left font-medium py-2">Gateway</th>
                <th className="text-right font-medium px-3 py-2">Amount</th>
              </tr>
            </thead>
            <tbody>
              {timeline.payments.map((p) => (
                <tr key={p.id} className="border-t border-border/60">
                  <td className="px-3 py-2 font-mono text-xs">{p.id}</td>
                  <td className="py-2 font-mono text-xs">{p.orderId}</td>
                  <td className="py-2"><StatusPill tone={p.status === "Paid" ? "success" : p.status === "Failed" ? "danger" : "warning"}>{p.status}</StatusPill></td>
                  <td className="py-2 text-xs">{p.gateway}</td>
                  <td className="px-3 py-2 text-right font-semibold tabular-nums">₹{p.amount?.toLocaleString?.() ?? p.amount}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function DeliveryTab({ loading, error, timeline }: TimelineTabProps) {
  return (
    <>
      {timelineHeader("Delhivery shipments")}
      {timelineStatusBanner(loading, error)}
      {!loading && !error && (timeline?.shipments?.length ?? 0) === 0 && (
        <EmptyTab icon={Truck} text="No shipments for this customer yet." />
      )}
      {timeline && timeline.shipments.length > 0 && (
        <div className="overflow-x-auto" data-testid="customer-shipments-list">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left font-medium px-3 py-2">AWB</th>
                <th className="text-left font-medium py-2">Order</th>
                <th className="text-left font-medium py-2">Status</th>
                <th className="text-left font-medium py-2">Courier</th>
                <th className="text-left font-medium py-2">ETA</th>
              </tr>
            </thead>
            <tbody>
              {timeline.shipments.map((s) => (
                <tr key={s.awb} className="border-t border-border/60">
                  <td className="px-3 py-2 font-mono text-xs">{s.awb}</td>
                  <td className="py-2 font-mono text-xs">{s.orderId}</td>
                  <td className="py-2"><StatusPill tone={s.status === "Delivered" ? "success" : s.status === "RTO" ? "danger" : "info"}>{s.status}</StatusPill></td>
                  <td className="py-2 text-xs">{s.courier}</td>
                  <td className="py-2 text-xs">{s.eta || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function EmptyTab({ icon: Icon, text }: { icon: any; text: string }) {
  return (
    <div className="text-center py-12">
      <Icon className="h-8 w-8 mx-auto text-muted-foreground mb-2" />
      <div className="text-sm text-muted-foreground">{text}</div>
    </div>
  );
}

interface WhatsAppTabProps {
  timeline: WhatsAppCustomerTimeline | null;
  loading: boolean;
}

function WhatsAppTab({ timeline, loading }: WhatsAppTabProps) {
  if (loading) {
    return (
      <div className="text-sm text-muted-foreground text-center py-8">
        Loading WhatsApp timeline…
      </div>
    );
  }
  if (!timeline) {
    return (
      <EmptyTab
        icon={MessageSquare}
        text="No WhatsApp conversation yet. Inbound messages or manual templates will appear here."
      />
    );
  }
  if (timeline.conversations.length === 0) {
    return (
      <div className="space-y-4">
        <EmptyTab
          icon={MessageSquare}
          text="No WhatsApp conversation yet. Inbound messages or manual templates will appear here."
        />
        <div className="rounded-xl bg-muted/40 p-3 text-xs flex items-start gap-2">
          <Sparkles className="h-3.5 w-3.5 text-accent shrink-0 mt-0.5" />
          <div>
            <span className="font-medium text-foreground">AI suggestions</span>{" "}
            <StatusPill
              tone={
                timeline.aiSuggestions.enabled
                  ? "success"
                  : timeline.aiSuggestions.status === "auto_reply_off"
                    ? "warning"
                    : "neutral"
              }
            >
              {timeline.aiSuggestions.enabled
                ? "auto"
                : timeline.aiSuggestions.status}
            </StatusPill>
            <p className="text-muted-foreground mt-1">
              {timeline.aiSuggestions.message}
            </p>
          </div>
        </div>
      </div>
    );
  }
  const totalUnread = timeline.conversations.reduce(
    (sum, c) => sum + c.unreadCount,
    0,
  );
  const messageItems = timeline.items.filter((item) => item.kind === "message");
  const noteItems = timeline.items.filter(
    (item) => item.kind === "internal_note",
  );
  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="font-display text-lg font-semibold flex items-center gap-2">
            <MessageSquare className="h-5 w-5 text-primary" />
            WhatsApp timeline
          </h3>
          <p className="text-xs text-muted-foreground">
            {timeline.conversations.length} conversation
            {timeline.conversations.length === 1 ? "" : "s"} · unread:{" "}
            {totalUnread}
          </p>
        </div>
        <Link to="/whatsapp-inbox">
          <Button size="sm" variant="outline">
            Open in Inbox
          </Button>
        </Link>
      </div>

      <div className="rounded-xl bg-muted/40 p-3 text-xs flex items-start gap-2">
        <Sparkles className="h-3.5 w-3.5 text-accent shrink-0 mt-0.5" />
        <div>
          <span className="font-medium text-foreground">AI suggestions</span>{" "}
          <StatusPill tone="neutral">{timeline.aiSuggestions.status}</StatusPill>
          <p className="text-muted-foreground mt-1">
            {timeline.aiSuggestions.message}
          </p>
        </div>
      </div>

      {timeline.conversations.length > 0 && (
        <div className="rounded-xl bg-background border border-border p-3 text-sm">
          <div className="flex items-center justify-between text-xs text-muted-foreground mb-1">
            <span>Active conversation</span>
            <StatusPill tone="info">
              {timeline.conversations[0].status}
            </StatusPill>
          </div>
          <div className="font-medium">
            {timeline.conversations[0].subject ||
              timeline.conversations[0].lastMessageText ||
              "—"}
          </div>
        </div>
      )}

      {messageItems.length > 0 && (
        <div className="space-y-2 max-h-[320px] overflow-auto scrollbar-thin pr-1">
          {messageItems.map((item) => {
            const message = item.data as WhatsAppMessage;
            const outbound = message.direction === "outbound";
            return (
              <div
                key={item.id}
                className={`rounded-lg border border-border px-3 py-2 ${
                  outbound ? "bg-gradient-emerald-soft" : "bg-muted/40"
                }`}
              >
                <div className="flex items-center justify-between text-[10px] uppercase tracking-wider text-muted-foreground">
                  <span>{outbound ? "Outbound" : "Inbound"}</span>
                  <span>{relativeTime(item.occurredAt)}</span>
                </div>
                {message.templateName && (
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground mt-0.5">
                    template · {message.templateName}
                  </div>
                )}
                <div className="text-sm mt-1 break-words">{message.body}</div>
                <div className="mt-1">
                  <StatusPill
                    tone={
                      message.status === "delivered" ||
                      message.status === "read"
                        ? "success"
                        : message.status === "failed"
                          ? "danger"
                          : "info"
                    }
                  >
                    {message.status === "delivered" && (
                      <CheckCheck className="h-3 w-3 mr-0.5" />
                    )}
                    {message.status}
                  </StatusPill>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {noteItems.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-xs uppercase tracking-wider text-muted-foreground">
            Internal notes
          </div>
          {noteItems.map((item) => {
            const note = item.data as WhatsAppInternalNote;
            return (
              <div
                key={item.id}
                className="rounded-lg bg-muted/30 px-2.5 py-1.5 text-xs"
              >
                <div className="flex items-center justify-between text-[10px] uppercase tracking-wider text-muted-foreground">
                  <span>{note.authorName || "operator"}</span>
                  <span>{relativeTime(item.occurredAt)}</span>
                </div>
                <div className="text-foreground/90 mt-0.5">{note.body}</div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}