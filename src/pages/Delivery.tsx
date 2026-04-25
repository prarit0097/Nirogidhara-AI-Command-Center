import { useEffect, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill, toneForStatus } from "@/components/StatusPill";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { api } from "@/services/api";
import { CheckCircle2, Circle, MapPin, Package, Truck } from "lucide-react";

const LIFECYCLE = ["Confirmed", "AWB Generated", "Pickup Scheduled", "In Transit", "Out for Delivery", "Delivered / RTO"];

export default function Delivery() {
  const [shipments, setShipments] = useState<any[]>([]);
  const [active, setActive] = useState<any | null>(null);
  useEffect(() => { api.getShipments().then(setShipments); }, []);

  return (
    <>
      <PageHeader eyebrow="Operations" title="Delhivery & Delivery Tracking"
        description="Live courier tracking. Mock UI — connect /api/shipments and Delhivery webhooks later."
      />

      <div className="surface-card p-6 mb-6 bg-gradient-leaf">
        <h3 className="font-display text-lg font-semibold mb-4">Shipment lifecycle</h3>
        <div className="flex flex-wrap items-center gap-2">
          {LIFECYCLE.map((s, i) => (
            <div key={s} className="flex items-center gap-2">
              <span className={`px-3 py-1.5 rounded-full text-xs font-medium ${i < 4 ? "bg-primary text-primary-foreground" : "bg-muted text-foreground"}`}>{s}</span>
              {i < LIFECYCLE.length - 1 && <span className="text-muted-foreground">→</span>}
            </div>
          ))}
        </div>
      </div>

      <div className="surface-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[900px]">
            <thead className="bg-muted/30 text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left font-medium px-6 py-3">AWB</th>
                <th className="text-left font-medium py-3">Order</th>
                <th className="text-left font-medium py-3">Customer</th>
                <th className="text-left font-medium py-3">Destination</th>
                <th className="text-left font-medium py-3">Courier</th>
                <th className="text-left font-medium py-3">Status</th>
                <th className="text-left font-medium px-6 py-3">ETA</th>
              </tr>
            </thead>
            <tbody>
              {shipments.map((s) => (
                <tr key={s.awb} onClick={() => setActive(s)} className="border-t border-border/60 hover:bg-muted/30 cursor-pointer">
                  <td className="px-6 py-3 font-mono text-xs">{s.awb}</td>
                  <td className="py-3 font-mono text-xs">{s.orderId}</td>
                  <td className="py-3">{s.customer}</td>
                  <td className="py-3"><MapPin className="h-3 w-3 inline mr-1 text-muted-foreground" />{s.city}, {s.state}</td>
                  <td className="py-3">{s.courier}</td>
                  <td className="py-3"><StatusPill tone={toneForStatus(s.status)}>{s.status}</StatusPill></td>
                  <td className="px-6 py-3">{s.eta}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <Sheet open={!!active} onOpenChange={() => setActive(null)}>
        <SheetContent className="sm:max-w-md w-full">
          {active && (
            <>
              <SheetHeader>
                <SheetTitle className="font-display text-2xl flex items-center gap-2"><Package className="h-5 w-5 text-primary" />{active.awb}</SheetTitle>
              </SheetHeader>
              <div className="mt-4 text-sm">
                <div className="font-medium">{active.customer}</div>
                <div className="text-muted-foreground">{active.city}, {active.state} · ETA {active.eta}</div>
              </div>
              <div className="mt-6">
                <div className="text-xs uppercase tracking-wider text-muted-foreground mb-3">Delhivery timeline</div>
                <ol className="relative border-l-2 border-border ml-3 space-y-4">
                  {active.timeline.map((t: any, i: number) => (
                    <li key={i} className="ml-4">
                      <span className={`absolute -left-[10px] mt-1 grid place-items-center h-5 w-5 rounded-full ring-4 ring-background ${t.done ? "bg-success text-success-foreground" : "bg-muted text-muted-foreground"}`}>
                        {t.done ? <CheckCircle2 className="h-3 w-3" /> : <Circle className="h-2 w-2" />}
                      </span>
                      <div className="text-sm font-medium">{t.step}</div>
                      <div className="text-xs text-muted-foreground">{t.at}</div>
                    </li>
                  ))}
                </ol>
              </div>
              <div className="mt-6 rounded-xl bg-info/10 border border-info/20 p-3 text-xs text-info">
                <Truck className="h-4 w-4 inline mr-1.5" />Delivery day reminder: scheduled for tomorrow 09:00 IST.
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </>
  );
}