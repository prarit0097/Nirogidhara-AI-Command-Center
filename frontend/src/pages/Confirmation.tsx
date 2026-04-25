import { useEffect, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { api } from "@/services/api";
import { CheckCircle2, Clock, Shield, ShieldAlert, X } from "lucide-react";
import { toast } from "sonner";

const STEPS = ["name", "address", "product", "amount", "intent"];

export default function Confirmation() {
  const [queue, setQueue] = useState<any[]>([]);
  useEffect(() => { api.getConfirmationQueue().then(setQueue); }, []);

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

      <div className="grid lg:grid-cols-2 gap-4">
        {queue.map((o) => (
          <ConfirmationCard key={o.id} order={o} />
        ))}
      </div>
    </>
  );
}

function ConfirmationCard({ order }: { order: any }) {
  const [check, setCheck] = useState<Record<string, boolean>>({});
  const completed = STEPS.filter((s) => check[s]).length;
  return (
    <div className="surface-card p-5 hover:shadow-elevated transition">
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
        <Button size="sm" className="bg-gradient-hero text-primary-foreground" onClick={() => toast.success(`${order.id} confirmed`)}>
          <CheckCircle2 className="h-3.5 w-3.5 mr-1" />Confirmed
        </Button>
        <Button size="sm" variant="outline" onClick={() => toast.warning(`${order.id} sent to RTO Rescue`)}>
          <Shield className="h-3.5 w-3.5 mr-1" />Rescue needed
        </Button>
        <Button size="sm" variant="outline" className="text-destructive hover:text-destructive" onClick={() => toast.error(`${order.id} cancelled`)}>
          <X className="h-3.5 w-3.5 mr-1" />Cancelled
        </Button>
      </div>
    </div>
  );
}