import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { api } from "@/services/api";
import type { OrderStage } from "@/types/domain";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Clock, CreditCard, IndianRupee, Loader2, MapPin, ShieldAlert, User } from "lucide-react";
import { toast } from "sonner";

const COLUMNS = ["New Lead", "Interested", "Payment Link Sent", "Order Punched", "Confirmation Pending", "Confirmed", "Dispatched", "Out for Delivery", "Delivered", "RTO"];

const STAGE_TONE: Record<string, any> = {
  "New Lead": "accent", "Interested": "info", "Payment Link Sent": "info",
  "Order Punched": "info", "Confirmation Pending": "warning", "Confirmed": "success",
  "Dispatched": "info", "Out for Delivery": "info", "Delivered": "success", "RTO": "danger",
};

// Phase 16B — safe internal transitions allowed from the Orders detail sheet.
// This is a deliberate subset of the full Order.Stage enum: transitions that
// would imply a real external side-effect (Dispatched / Out for Delivery /
// Delivered / RTO) are NOT exposed here — those land via their own backend
// services (Phase 7G dispatch, Delhivery tracking webhook, payment webhook).
// "Confirmation Pending" is also excluded so operators are forced to use the
// dedicated Confirmation Queue checklist surface.
const ORDER_NEXT_STAGE_OPTIONS: Partial<Record<OrderStage, Array<{ stage: OrderStage; label: string }>>> = {
  "New Lead": [{ stage: "Interested", label: "Mark Interested" }],
  "Interested": [{ stage: "Payment Link Sent", label: "Mark Payment Link Sent" }],
  "Payment Link Sent": [{ stage: "Order Punched", label: "Mark Order Punched" }],
  "Order Punched": [{ stage: "Confirmation Pending", label: "Move to Confirmation" }],
};

export default function Orders() {
  const [orders, setOrders] = useState<any[]>([]);
  const [active, setActive] = useState<any | null>(null);

  const loadOrders = useCallback(() => {
    api.getOrders().then(setOrders);
  }, []);

  useEffect(() => { loadOrders(); }, [loadOrders]);

  return (
    <>
      <PageHeader eyebrow="Operations" title="Orders Pipeline"
        description="End-to-end visibility from lead to delivery. Drag-style kanban with order age, RTO risk and assigned agent."
      />

      <div className="overflow-x-auto -mx-4 px-4 pb-2">
        <div className="flex gap-4 min-w-max">
          {COLUMNS.map((col) => {
            const items = orders.filter((o) => o.stage === col);
            return (
              <div key={col} className="w-[280px] shrink-0">
                <div className="flex items-center justify-between mb-3 px-1">
                  <div className="flex items-center gap-2">
                    <span className={`h-2 w-2 rounded-full bg-${STAGE_TONE[col]} bg-current`} />
                    <h3 className="font-medium text-sm">{col}</h3>
                  </div>
                  <span className="text-xs text-muted-foreground tabular-nums">{items.length}</span>
                </div>
                <div className="space-y-2.5 min-h-[120px]">
                  {items.map((o) => (
                    <button
                      key={o.id}
                      onClick={() => setActive(o)}
                      className="w-full text-left surface-card p-3.5 hover:shadow-elevated transition-all"
                    >
                      <div className="flex items-start justify-between mb-2">
                        <div className="font-medium text-sm truncate">{o.customerName}</div>
                        <StatusPill tone={o.rtoRisk === "High" ? "danger" : o.rtoRisk === "Medium" ? "warning" : "success"}>
                          {o.rtoRisk}
                        </StatusPill>
                      </div>
                      <div className="text-[11px] text-muted-foreground mb-2.5 truncate">{o.product} · {o.city}</div>
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-semibold tabular-nums">₹{o.amount.toLocaleString()}</span>
                        <StatusPill tone={o.paymentStatus === "Paid" ? "success" : o.paymentStatus === "Failed" ? "danger" : "warning"}>{o.paymentStatus}</StatusPill>
                      </div>
                      <div className="mt-2 pt-2 border-t border-border flex items-center justify-between text-[11px] text-muted-foreground">
                        <span className="truncate">{o.agent}</span>
                        <span className="inline-flex items-center gap-1"><Clock className="h-3 w-3" />{o.ageHours}h</span>
                      </div>
                    </button>
                  ))}
                  {items.length === 0 && (
                    <div className="rounded-xl border-2 border-dashed border-border/60 p-4 text-center text-xs text-muted-foreground">
                      No orders
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <Sheet open={!!active} onOpenChange={() => setActive(null)}>
        <SheetContent className="sm:max-w-md w-full overflow-y-auto">
          {active && (
            <OrderDetailSheet
              order={active}
              onTransitioned={() => {
                loadOrders();
                setActive(null);
              }}
            />
          )}
        </SheetContent>
      </Sheet>
    </>
  );
}

interface OrderDetailSheetProps {
  order: any;
  onTransitioned: () => void;
}

function OrderDetailSheet({ order, onTransitioned }: OrderDetailSheetProps) {
  const [pendingStage, setPendingStage] = useState<OrderStage | null>(null);
  const stage: OrderStage = order.stage;
  const options = ORDER_NEXT_STAGE_OPTIONS[stage] ?? [];

  const handleTransition = async (nextStage: OrderStage, label: string) => {
    if (pendingStage) return;
    setPendingStage(nextStage);
    try {
      await api.transitionOrder(order.id, nextStage);
      toast.success(`${order.id} → ${nextStage}`);
      onTransitioned();
    } catch (err) {
      const message = err instanceof Error ? err.message : `Transition failed`;
      toast.error(`Could not ${label}: ${message.slice(0, 180)}`);
    } finally {
      setPendingStage(null);
    }
  };

  return (
    <>
      <SheetHeader>
        <SheetTitle className="font-display text-2xl">{order.id}</SheetTitle>
        <SheetDescription>{order.product} · {order.quantity} pack</SheetDescription>
      </SheetHeader>
      <div className="mt-6 space-y-4">
        <Row icon={User} label="Customer" value={order.customerName} sub={order.phone} />
        <Row icon={MapPin} label="Address" value={`${order.city}, ${order.state}`} />
        <Row icon={IndianRupee} label="Amount" value={`₹${order.amount.toLocaleString()}`} sub={`${order.discountPct}% discount`} />
        <Row icon={CreditCard} label="Payment" value={order.paymentStatus} sub={order.advancePaid ? `Advance ₹${order.advanceAmount}` : "No advance"} />
        <Row icon={ShieldAlert} label="RTO Risk" value={`${order.rtoRisk} (${order.rtoScore}/100)`} />
        <div className="rounded-xl bg-muted/40 p-3 space-y-2">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Current stage</div>
          <StatusPill tone={STAGE_TONE[stage] ?? "info"}>{stage}</StatusPill>
        </div>
        {options.length > 0 ? (
          <div className="space-y-2" data-testid={`order-transition-options-${order.id}`}>
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Safe transitions</div>
            <div className="flex flex-wrap gap-2">
              {options.map((opt) => (
                <Button
                  key={opt.stage}
                  size="sm"
                  variant="outline"
                  disabled={!!pendingStage}
                  onClick={() => handleTransition(opt.stage, opt.label)}
                  data-testid={`order-transition-${order.id}-${opt.stage.replace(/\s+/g, "-").toLowerCase()}`}
                >
                  {pendingStage === opt.stage ? (
                    <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                  ) : null}
                  {pendingStage === opt.stage ? "Working…" : opt.label}
                </Button>
              ))}
            </div>
            <div className="text-[11px] text-muted-foreground">
              Internal stage transitions only — no shipment, payment, WhatsApp or call side-effects fire from this surface.
            </div>
          </div>
        ) : (
          <div className="rounded-lg bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            {stage === "Confirmation Pending"
              ? "Use the Confirmation Queue checklist to action this order."
              : "No safe internal transitions available from this stage."}
          </div>
        )}
      </div>
    </>
  );
}

function Row({ icon: Icon, label, value, sub }: any) {
  return (
    <div className="flex items-start gap-3 rounded-xl bg-muted/40 p-3">
      <Icon className="h-4 w-4 mt-0.5 text-muted-foreground" />
      <div>
        <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</div>
        <div className="text-sm font-medium">{value}</div>
        {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
      </div>
    </div>
  );
}