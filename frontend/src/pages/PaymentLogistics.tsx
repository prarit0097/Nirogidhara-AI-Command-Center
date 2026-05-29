import { PageHeader } from "@/components/PageHeader";
import { api } from "@/services/api";
import type {
  IntegrationProviderReadiness,
  PaymentLogisticsReadiness,
  PaymentLogisticsRecentEvents,
} from "@/types/domain";
import {
  AlertTriangle,
  CreditCard,
  Lock,
  ShieldCheck,
  Truck,
} from "lucide-react";
import { useEffect, useState } from "react";

const STATUS_STYLES: Record<string, string> = {
  ready: "bg-success/15 text-success",
  blocked: "bg-destructive/20 text-destructive",
  misconfigured: "bg-warning/20 text-warning",
  unavailable: "bg-muted text-muted-foreground",
};

export default function PaymentLogistics() {
  const [readiness, setReadiness] = useState<PaymentLogisticsReadiness | null>(null);
  const [events, setEvents] = useState<PaymentLogisticsRecentEvents | null>(null);
  const [loading, setLoading] = useState(true);
  const [errored, setErrored] = useState(false);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.getPaymentLogisticsReadiness().then(setReadiness),
      api
        .getPaymentLogisticsRecentEvents()
        .then(setEvents)
        .catch(() => setEvents(null)),
    ])
      .catch(() => {
        setReadiness(null);
        setErrored(true);
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="h-96 grid place-items-center text-muted-foreground">
        Loading payment &amp; logistics readiness...
      </div>
    );
  }

  if (errored || !readiness) {
    return (
      <div data-testid="payment-logistics-page">
        <PageHeader
          eyebrow="Operations"
          title="Payment &amp; Logistics"
          description="Integration hardening readiness."
        />
        <div
          data-testid="payment-logistics-error"
          className="surface-elevated p-6 text-destructive text-[14px]"
        >
          Could not load readiness. Please retry.
        </div>
      </div>
    );
  }

  const safety = readiness.safety;

  return (
    <div data-testid="payment-logistics-page">
      <PageHeader
        eyebrow="Operations"
        title="Payment &amp; Logistics"
        description="Integration hardening readiness for Razorpay, PayU, and Delhivery. Hardening mode only — no live provider action is triggered from this page."
      />

      {/* No-side-effect safety banner */}
      <div
        data-testid="payment-logistics-safety-copy"
        className="mb-6 flex items-start gap-2 rounded-xl border border-border bg-muted/40 px-4 py-3 text-[13px] text-muted-foreground"
      >
        <ShieldCheck className="h-4 w-4 mt-0.5 shrink-0 text-success" />
        <span>
          Hardening mode only — this page does NOT create live payment links,
          capture/refund payments, or book Delhivery shipments unless a future
          explicit Director live-pilot gate is approved. No WhatsApp / payment /
          courier / Vapi / AI-provider action is triggered.
        </span>
      </div>

      {/* Safety summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <SafetyChip
          label="AI"
          value={safety.aiPaused ? "Paused" : "Running"}
          tone={safety.aiPaused ? "success" : "warning"}
        />
        <SafetyChip
          label="Sandbox"
          value={safety.sandboxOn ? "ON" : "OFF"}
          tone="success"
        />
        <SafetyChip
          label="Live provider actions"
          value={safety.providerLiveActionsLocked ? "Locked" : "Open"}
          tone={safety.providerLiveActionsLocked ? "success" : "danger"}
        />
        <SafetyChip label="Mode" value={`Phase ${safety.phase} hardening`} />
      </div>

      {/* Payments */}
      <h2 className="font-display text-lg font-semibold flex items-center gap-2 mb-3">
        <CreditCard className="h-5 w-5 text-accent" /> Payment readiness
      </h2>
      <div className="grid md:grid-cols-2 gap-4 mb-6" data-testid="payment-readiness-cards">
        {readiness.payments.map((p) => (
          <ProviderCard key={p.provider} provider={p} />
        ))}
      </div>

      {/* Logistics */}
      <h2 className="font-display text-lg font-semibold flex items-center gap-2 mb-3">
        <Truck className="h-5 w-5 text-accent" /> Logistics readiness
      </h2>
      <div className="grid md:grid-cols-2 gap-4 mb-6" data-testid="logistics-readiness-cards">
        {readiness.logistics.map((p) => (
          <ProviderCard key={p.provider} provider={p} />
        ))}
      </div>

      {/* Order workflow gates */}
      <div className="surface-elevated p-6 mb-6">
        <h3 className="font-display text-lg font-semibold flex items-center gap-2 mb-3">
          <Lock className="h-5 w-5 text-primary" /> Order workflow gates
        </h3>
        <ul className="space-y-2 text-[13.5px]">
          <GateRow label="Payment gate" gate={readiness.orderWorkflowGates.paymentGate} />
          <GateRow label="Shipment gate" gate={readiness.orderWorkflowGates.shipmentGate} />
        </ul>
      </div>

      {/* Recent internal events */}
      {events && (
        <div className="surface-elevated p-6">
          <h3 className="font-display text-lg font-semibold mb-3">
            Recent internal events
          </h3>
          <div className="grid md:grid-cols-2 gap-4 text-[13px]">
            <div>
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-1">
                Payments ({events.paymentTotal})
              </div>
              {events.payments.length === 0 ? (
                <p className="text-muted-foreground">No payment records.</p>
              ) : (
                <ul className="space-y-1">
                  {events.payments.slice(0, 8).map((p) => (
                    <li key={p.id} className="flex justify-between gap-2">
                      <span className="font-mono text-[12px]">{p.id}</span>
                      <span>{p.gateway}</span>
                      <span className="capitalize">{p.status}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-1">
                Shipments ({events.shipmentTotal})
              </div>
              {events.shipments.length === 0 ? (
                <p className="text-muted-foreground">No shipment records.</p>
              ) : (
                <ul className="space-y-1">
                  {events.shipments.slice(0, 8).map((s, idx) => (
                    <li key={`${s.awbLast6}-${idx}`} className="flex justify-between gap-2">
                      <span className="font-mono text-[12px]">…{s.awbLast6}</span>
                      <span>{s.courier}</span>
                      <span className="capitalize">{s.status}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function SafetyChip({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "success" | "warning" | "danger";
}) {
  const toneClass =
    tone === "success"
      ? "text-success"
      : tone === "warning"
        ? "text-warning"
        : tone === "danger"
          ? "text-destructive"
          : "text-foreground";
  return (
    <div className="rounded-lg border border-border bg-muted/30 px-3 py-2">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className={`text-[15px] font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}

function ProviderCard({ provider }: { provider: IntegrationProviderReadiness }) {
  return (
    <div
      className="surface-elevated p-5"
      data-testid={`provider-card-${provider.provider}`}
    >
      <div className="flex items-center justify-between gap-3 mb-2">
        <h3 className="font-display text-base font-semibold">{provider.label}</h3>
        <span
          data-testid={`provider-status-${provider.provider}`}
          className={`rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider ${
            STATUS_STYLES[provider.status] ?? STATUS_STYLES.unavailable
          }`}
        >
          {provider.status}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2 text-[12.5px] mb-3">
        <Field label="Mode" value={provider.mode} />
        <Field label="Configured" value={provider.configured ? "Yes" : "No"} />
        <Field label="Live enabled" value={provider.liveEnabled ? "Yes" : "No"} />
        <Field
          label="Live gate"
          value={provider.liveGatePresent ? "Present" : "Required (absent)"}
        />
      </div>
      {provider.blockedReasons.length > 0 && (
        <div className="rounded-lg bg-muted/50 p-2.5 text-[12px] mb-2">
          <div className="flex items-center gap-1 font-medium text-warning mb-1">
            <AlertTriangle className="h-3.5 w-3.5" /> Blocked reasons
          </div>
          <ul className="list-disc pl-4 space-y-0.5 text-muted-foreground">
            {provider.blockedReasons.map((r, idx) => (
              <li key={idx}>{r}</li>
            ))}
          </ul>
        </div>
      )}
      {provider.safeActions.length > 0 && (
        <div className="text-[12px] text-muted-foreground">
          <span className="font-medium">Safe actions:</span>{" "}
          {provider.safeActions.join(" ")}
        </div>
      )}
      {/* No live action button is rendered — live is gated/blocked. */}
      <div className="mt-3 text-[11px] text-muted-foreground italic">
        Live actions disabled — Director live gate required.
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10.5px] uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="font-medium">{value}</div>
    </div>
  );
}

function GateRow({
  label,
  gate,
}: {
  label: string;
  gate: { liveEnabled: boolean; liveGatePresent: boolean; note: string };
}) {
  return (
    <li className="flex flex-col gap-0.5">
      <div className="flex items-center justify-between gap-3">
        <span className="font-medium">{label}</span>
        <span
          className={`text-[12px] ${gate.liveEnabled ? "text-destructive" : "text-success"}`}
        >
          {gate.liveEnabled ? "Live enabled" : "Live blocked"}
        </span>
      </div>
      <span className="text-[12px] text-muted-foreground">{gate.note}</span>
    </li>
  );
}
