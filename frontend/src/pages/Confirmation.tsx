import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { api } from "@/services/api";
import type { ConfirmationOutcome } from "@/types/domain";
import { CheckCircle2, Clock, Loader2, Shield, ShieldAlert, X } from "lucide-react";
import { toast } from "sonner";

const STEPS = ["name", "address", "product", "amount", "intent"];

export default function Confirmation() {
  const [queue, setQueue] = useState<any[]>([]);
  const [loadingQueue, setLoadingQueue] = useState(true);

  const refresh = useCallback(async () => {
    setLoadingQueue(true);
    try {
      const rows = await api.getConfirmationQueue();
      setQueue(rows ?? []);
    } finally {
      setLoadingQueue(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <>
      <PageHeader eyebrow="Operations" title="Confirmation Queue"
        description="Verify name, address, product, amount and intent ~24 hours after order. Catch weak orders before they ship."
      />

      <div className="surface-card p-6 mb-6 bg-gradient-leaf">
        <h3 className="font-display text-lg font-semibold mb-3">Confirmation workflow</h3>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {["Order Punched", "Wait ~24h", "Confirmation Call", "Name", "Address", "Product", "Amount", "Intent", "CRM Update"].map((s, i, arr) => (
            <div key={s} className="flex items-center gap-2">
              <span className={`px-3 py-1.5 rounded-full text-xs font-medium ${i < 3 ? "bg-success text-success-foreground" : "bg-muted text-foreground"}`}>{s}</span>
              {i < arr.length - 1 && <span className="text-muted-foreground">→</span>}
            </div>
          ))}
        </div>
      </div>

      {loadingQueue && queue.length === 0 ? (
        <div className="surface-card p-8 text-center text-sm text-muted-foreground" data-testid="confirmation-loading">
          <Loader2 className="h-5 w-5 mx-auto mb-2 animate-spin opacity-60" />
          Loading confirmation queue…
        </div>
      ) : queue.length === 0 ? (
        <div className="surface-card p-8 text-center text-sm text-muted-foreground" data-testid="confirmation-empty">
          No orders waiting for confirmation right now.
        </div>
      ) : (
        <div className="grid lg:grid-cols-2 gap-4">
          {queue.map((o) => (
            <ConfirmationCard key={o.id} order={o} onActionDone={refresh} />
          ))}
        </div>
      )}
    </>
  );
}

interface ConfirmationCardProps {
  order: any;
  onActionDone: () => void;
}

function ConfirmationCard({ order, onActionDone }: ConfirmationCardProps) {
  const [check, setCheck] = useState<Record<string, boolean>>({});
  const [pendingAction, setPendingAction] = useState<ConfirmationOutcome | null>(null);
  const completed = STEPS.filter((s) => check[s]).length;

  const handleOutcome = async (outcome: ConfirmationOutcome, label: string) => {
    if (pendingAction) return;
    setPendingAction(outcome);
    try {
      await api.confirmOrder(order.id, outcome);
      if (outcome === "confirmed") toast.success(`${order.id} confirmed`);
      else if (outcome === "rescue_needed") toast.warning(`${order.id} sent to RTO Rescue`);
      else toast.info(`${order.id} cancelled`);
      onActionDone();
    } catch (err) {
      const message = err instanceof Error ? err.message : `${label} failed`;
      toast.error(`Could not ${label}: ${message.slice(0, 160)}`);
    } finally {
      setPendingAction(null);
    }
  };

  return (
    <div className="surface-card p-5 hover:shadow-elevated transition" data-testid={`confirmation-card-${order.id}`}>
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="font-display text-lg font-semibold">{order.customerName}</div>
          <div className="text-xs text-muted-foreground">{order.id} · {order.product} · ₹{order.amount.toLocaleString()}</div>
          <div className="text-xs text-muted-foreground">{order.city}, {order.state}</div>
        </div>
        <div className="text-right">
          <StatusPill tone={order.hoursWaiting > 24 ? "warning" : "info"} icon={<Clock className="h-3 w-3" />}>{order.hoursWaiting}h waiting</StatusPill>
          <div className="mt-2"><StatusPill tone={order.addressConfidence > 75 ? "success" : "warning"}>Addr conf {order.addressConfidence}%</StatusPill></div>
        </div>
      </div>

      <div className="rounded-xl bg-muted/50 p-3 mb-3">
        <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-2">Checklist</div>
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
          {STEPS.map((s) => (
            <button key={s} onClick={() => setCheck((c) => ({ ...c, [s]: !c[s] }))}
              className={`text-xs px-2.5 py-2 rounded-lg border transition flex items-center gap-1.5 capitalize ${check[s] ? "bg-success/15 border-success/30 text-success" : "bg-background border-border hover:border-primary/30"}`}>
              <CheckCircle2 className={`h-3.5 w-3.5 ${check[s] ? "" : "opacity-30"}`} />{s}
            </button>
          ))}
        </div>
        <div className="h-1.5 rounded-full bg-background mt-3 overflow-hidden">
          <div className="h-full bg-success transition-all duration-300" style={{ width: `${(completed/5)*100}%` }} />
        </div>
      </div>

      {order.addressConfidence < 70 && (
        <div className="rounded-lg bg-warning/10 border border-warning/20 text-warning p-2.5 text-xs flex items-center gap-2 mb-3">
          <ShieldAlert className="h-3.5 w-3.5" /> Weak confirmation risk — verify pin code carefully.
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          className="bg-gradient-hero text-primary-foreground"
          disabled={!!pendingAction}
          onClick={() => handleOutcome("confirmed", "confirm")}
          data-testid={`confirmation-confirmed-${order.id}`}
        >
          {pendingAction === "confirmed" ? (
            <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
          ) : (
            <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
          )}
          {pendingAction === "confirmed" ? "Confirming…" : "Confirmed"}
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={!!pendingAction}
          onClick={() => handleOutcome("rescue_needed", "send to rescue")}
          data-testid={`confirmation-rescue-${order.id}`}
        >
          {pendingAction === "rescue_needed" ? (
            <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
          ) : (
            <Shield className="h-3.5 w-3.5 mr-1" />
          )}
          {pendingAction === "rescue_needed" ? "Working…" : "Rescue needed"}
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="text-destructive hover:text-destructive"
          disabled={!!pendingAction}
          onClick={() => handleOutcome("cancelled", "cancel")}
          data-testid={`confirmation-cancel-${order.id}`}
        >
          {pendingAction === "cancelled" ? (
            <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
          ) : (
            <X className="h-3.5 w-3.5 mr-1" />
          )}
          {pendingAction === "cancelled" ? "Cancelling…" : "Cancelled"}
        </Button>
      </div>
    </div>
  );
}
