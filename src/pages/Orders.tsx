import { useEffect, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { api } from "@/services/api";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Clock, CreditCard, IndianRupee, MapPin, ShieldAlert, User } from "lucide-react";

const COLUMNS = ["New Lead", "Interested", "Payment Link Sent", "Order Punched", "Confirmation Pending", "Confirmed", "Dispatched", "Out for Delivery", "Delivered", "RTO"];

const STAGE_TONE: Record<string, any> = {
  "New Lead": "accent", "Interested": "info", "Payment Link Sent": "info",
  "Order Punched": "info", "Confirmation Pending": "warning", "Confirmed": "success",
  "Dispatched": "info", "Out for Delivery": "info", "Delivered": "success", "RTO": "danger",
};

export default function Orders() {
  const [orders, setOrders] = useState<any[]>([]);
  const [active, setActive] = useState<any | null>(null);

  useEffect(() => { api.getOrders().then(setOrders); }, []);

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
            <>
              <SheetHeader>
                <SheetTitle className="font-display text-2xl">{active.id}</SheetTitle>
                <SheetDescription>{active.product} · {active.quantity} pack</SheetDescription>
              </SheetHeader>
              <div className="mt-6 space-y-4">
                <Row icon={User} label="Customer" value={active.customerName} sub={active.phone} />
                <Row icon={MapPin} label="Address" value={`${active.city}, ${active.state}`} />
                <Row icon={IndianRupee} label="Amount" value={`₹${active.amount.toLocaleString()}`} sub={`${active.discountPct}% discount`} />
                <Row icon={CreditCard} label="Payment" value={active.paymentStatus} sub={active.advancePaid ? `Advance ₹${active.advanceAmount}` : "No advance"} />
                <Row icon={ShieldAlert} label="RTO Risk" value={`${active.rtoRisk} (${active.rtoScore}/100)`} />
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
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