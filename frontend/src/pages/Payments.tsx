import { useEffect, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { MetricCard } from "@/components/MetricCard";
import { StatusPill, toneForStatus } from "@/components/StatusPill";
import { api } from "@/services/api";
import { Button } from "@/components/ui/button";
import { CreditCard, IndianRupee, RefreshCw, Send, Wallet, X } from "lucide-react";
import { toast } from "sonner";
import type { Payment } from "@/types/domain";

export default function Payments() {
  const [payments, setPayments] = useState<Payment[]>([]);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    api.getPayments().then(setPayments);
  }, []);

  const totals = payments.reduce(
    (acc, p) => {
      acc.total += p.amount;
      acc[p.status] = (acc[p.status] || 0) + 1;
      return acc;
    },
    { total: 0 } as Record<string, number>,
  );

  async function handleGenerateLink() {
    const orderId = window.prompt(
      "Enter order ID to generate a Razorpay payment link",
      "NRG-20410",
    );
    if (!orderId) return;
    const amountInput = window.prompt("Amount (₹)", "499");
    const amount = Number.parseInt(amountInput || "0", 10);
    if (!Number.isFinite(amount) || amount <= 0) {
      toast.error("Enter a valid amount");
      return;
    }
    setGenerating(true);
    try {
      const res = await api.createPaymentLink({
        orderId,
        amount,
        gateway: "Razorpay",
        type: "Advance",
        customerName: "",
        customerPhone: "",
        customerEmail: "",
      });
      try {
        await navigator.clipboard?.writeText(res.paymentUrl);
      } catch {
        /* clipboard may be unavailable; ignore */
      }
      toast.success(`Payment link ready · ${res.paymentId}`, {
        description: res.paymentUrl,
        duration: 8000,
      });
      api.getPayments().then(setPayments);
    } catch (error) {
      toast.error("Could not create payment link", {
        description: (error as Error).message,
      });
    } finally {
      setGenerating(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Operations"
        title="Payments"
        description="Razorpay & PayU reconciliation, advance ratio and refund queue. /api/payments/links/ creates a real test-mode link when RAZORPAY_MODE is set; mock by default."
        actions={
          <Button
            className="bg-gradient-hero text-primary-foreground"
            onClick={handleGenerateLink}
            disabled={generating}
          >
            <Send className="h-4 w-4 mr-1.5" />
            {generating ? "Generating…" : "Generate link"}
          </Button>
        }
      />

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <MetricCard icon={IndianRupee} label="Total volume" value={`₹${(totals.total/1000).toFixed(0)}K`} tone="primary" />
        <MetricCard icon={CreditCard} label="Paid" value={totals.Paid || 0} tone="success" />
        <MetricCard icon={Wallet} label="Pending" value={totals.Pending || 0} tone="warning" />
        <MetricCard icon={X} label="Failed / Refunded" value={(totals.Failed || 0) + (totals.Refunded || 0)} tone="danger" />
      </div>

      <div className="grid lg:grid-cols-2 gap-6 mb-6">
        <GatewayCard name="Razorpay" tone="info" payments={payments.filter((p) => p.gateway === "Razorpay")} />
        <GatewayCard name="PayU" tone="accent" payments={payments.filter((p) => p.gateway === "PayU")} />
      </div>

      <div className="surface-card overflow-hidden">
        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
          <h3 className="font-display text-lg font-semibold">Reconciliation</h3>
          <Button size="sm" variant="ghost"><RefreshCw className="h-3.5 w-3.5 mr-1" />Refresh</Button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[800px]">
            <thead className="bg-muted/30 text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left font-medium px-6 py-3">Pay ID</th>
                <th className="text-left font-medium py-3">Order</th>
                <th className="text-left font-medium py-3">Customer</th>
                <th className="text-right font-medium py-3">Amount</th>
                <th className="text-left font-medium py-3">Type</th>
                <th className="text-left font-medium py-3">Gateway</th>
                <th className="text-left font-medium py-3">Status</th>
                <th className="text-left font-medium px-6 py-3">Time</th>
              </tr>
            </thead>
            <tbody>
              {payments.map((p) => (
                <tr key={p.id} className="border-t border-border/60 hover:bg-muted/20">
                  <td className="px-6 py-3 font-mono text-xs">{p.id}</td>
                  <td className="py-3 font-mono text-xs">{p.orderId}</td>
                  <td className="py-3">{p.customer}</td>
                  <td className="py-3 text-right font-semibold tabular-nums">₹{p.amount.toLocaleString()}</td>
                  <td className="py-3">{p.type}</td>
                  <td className="py-3">{p.gateway}</td>
                  <td className="py-3"><StatusPill tone={toneForStatus(p.status)}>{p.status}</StatusPill></td>
                  <td className="px-6 py-3 text-muted-foreground">{p.time}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

function GatewayCard({ name, tone, payments }: { name: string; tone: any; payments: any[] }) {
  const paid = payments.filter((p) => p.status === "Paid").length;
  const pending = payments.filter((p) => p.status === "Pending").length;
  const failed = payments.filter((p) => p.status === "Failed").length;
  return (
    <div className="surface-card p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-display text-xl font-semibold">{name}</h3>
        <StatusPill tone={tone}>Live</StatusPill>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <div><div className="text-xs text-muted-foreground">Paid</div><div className="font-display text-2xl font-semibold text-success">{paid}</div></div>
        <div><div className="text-xs text-muted-foreground">Pending</div><div className="font-display text-2xl font-semibold text-warning">{pending}</div></div>
        <div><div className="text-xs text-muted-foreground">Failed</div><div className="font-display text-2xl font-semibold text-destructive">{failed}</div></div>
      </div>
    </div>
  );
}