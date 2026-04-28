import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { api } from "@/services/api";
import type { WhatsAppProviderStatus } from "@/types/domain";
import {
  Boxes,
  KeyRound,
  MessageSquare,
  Power,
  RotateCcw,
  ShieldCheck,
  ScrollText,
  Beaker,
} from "lucide-react";
import { toast } from "sonner";

export default function Settings() {
  const [data, setData] = useState<any>(null);
  const [killSwitch, setKillSwitch] = useState(false);
  const [sandbox, setSandbox] = useState(true);
  const [whatsappStatus, setWhatsappStatus] = useState<
    WhatsAppProviderStatus | null
  >(null);

  useEffect(() => {
    api.getSettingsMock().then(setData);
    api.getWhatsAppProviderStatus().then(setWhatsappStatus);
  }, []);
  if (!data) return <div className="h-96 grid place-items-center text-muted-foreground">Loading…</div>;

  return (
    <>
      <PageHeader eyebrow="System" title="Settings & Control Center"
        description="Roles, governance, AI safety controls, integrations and audit ledger — everything that keeps the system safe."
      />

      <div className="grid lg:grid-cols-3 gap-4 mb-6">
        <ControlCard icon={Power} tone="danger" title="AI Kill Switch" desc="Immediately pause all AI agents.">
          <Switch checked={killSwitch} onCheckedChange={(v) => { setKillSwitch(v); toast[v ? "error" : "success"](v ? "Kill Switch engaged" : "AI agents resumed"); }} />
        </ControlCard>
        <ControlCard icon={Beaker} tone="info" title="Sandbox Mode" desc="Run new prompts/playbooks in shadow mode first.">
          <Switch checked={sandbox} onCheckedChange={setSandbox} />
        </ControlCard>
        <ControlCard icon={RotateCcw} tone="warning" title="Rollback System" desc="Revert to last known-good prompts and pricing rules.">
          <Button variant="outline" size="sm" onClick={() => toast.success("Rolled back to v3.2")}>Rollback</Button>
        </ControlCard>
      </div>

      <div className="surface-card overflow-hidden mb-6">
        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
          <h3 className="font-display text-lg font-semibold flex items-center gap-2"><ShieldCheck className="h-5 w-5 text-primary" />AI Action Approval Matrix</h3>
          <StatusPill tone="info">v2.1</StatusPill>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[600px]">
            <thead className="bg-muted/30 text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left font-medium px-6 py-3">Action</th>
                <th className="text-left font-medium py-3">Policy</th>
                <th className="text-left font-medium px-6 py-3">Approver</th>
              </tr>
            </thead>
            <tbody>
              {data.approvalMatrix.map((a: any) => (
                <tr key={a.action} className="border-t border-border/60 hover:bg-muted/20">
                  <td className="px-6 py-3 font-medium">{a.action}</td>
                  <td className="py-3"><StatusPill tone={a.policy === "Auto" ? "success" : a.policy.includes("Hard") ? "danger" : a.policy.includes("Approval") ? "warning" : "info"}>{a.policy}</StatusPill></td>
                  <td className="px-6 py-3">{a.approver}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="surface-card p-6 mb-6">
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-3">
            <MessageSquare className="h-5 w-5 text-primary" />
            <div>
              <h3 className="font-display text-lg font-semibold">
                WhatsApp Business (WABA)
              </h3>
              <p className="text-xs text-muted-foreground">
                Phase 5A · Meta Cloud is the production target. Mock provider
                runs in local dev so no live messages go out without consent
                + approved template + Claim Vault.
              </p>
            </div>
          </div>
          <Link to="/whatsapp-templates">
            <Button size="sm" variant="outline">
              View templates
            </Button>
          </Link>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <WabaStatField
            label="Provider"
            value={whatsappStatus?.provider ?? "—"}
            tone={
              whatsappStatus?.provider === "meta_cloud"
                ? "success"
                : whatsappStatus?.provider === "mock"
                  ? "info"
                  : "warning"
            }
          />
          <WabaStatField
            label="Health"
            value={
              whatsappStatus
                ? whatsappStatus.healthy
                  ? "healthy"
                  : "unhealthy"
                : "—"
            }
            tone={whatsappStatus?.healthy ? "success" : "warning"}
          />
          <WabaStatField
            label="Phone number"
            value={whatsappStatus?.connection?.phoneNumber || "not set"}
            tone={
              whatsappStatus?.connection?.phoneNumber ? "neutral" : "warning"
            }
          />
          <WabaStatField
            label="Phone number id"
            value={whatsappStatus?.connection?.phoneNumberId || "not set"}
            tone={
              whatsappStatus?.connection?.phoneNumberId
                ? "neutral"
                : "warning"
            }
          />
          <WabaStatField
            label="Access token"
            value={whatsappStatus?.accessTokenSet ? "configured" : "missing"}
            tone={whatsappStatus?.accessTokenSet ? "success" : "warning"}
          />
          <WabaStatField
            label="Verify token"
            value={whatsappStatus?.verifyTokenSet ? "configured" : "missing"}
            tone={whatsappStatus?.verifyTokenSet ? "success" : "warning"}
          />
          <WabaStatField
            label="App secret"
            value={whatsappStatus?.appSecretSet ? "configured" : "missing"}
            tone={whatsappStatus?.appSecretSet ? "success" : "warning"}
          />
          <WabaStatField
            label="API version"
            value={whatsappStatus?.apiVersion ?? "—"}
            tone="neutral"
          />
        </div>

        {whatsappStatus?.devProviderEnabled && (
          <div className="mt-3 text-xs text-warning">
            Dev-only Baileys provider toggle is ENABLED. Production must keep
            <code> WHATSAPP_DEV_PROVIDER_ENABLED=false</code>.
          </div>
        )}
      </div>

      <div className="grid lg:grid-cols-2 gap-6 mb-6">
        <div className="surface-card p-6">
          <h3 className="font-display text-lg font-semibold mb-4 flex items-center gap-2"><Boxes className="h-5 w-5 text-primary" />Integrations</h3>
          <div className="space-y-2">
            {data.integrations.map((i: any) => (
              <div key={i.name} className="flex items-center justify-between rounded-xl bg-muted/40 p-3">
                <div>
                  <div className="font-medium">{i.name}</div>
                  <div className="text-xs text-muted-foreground">{i.purpose}</div>
                </div>
                <div className="flex items-center gap-2">
                  <StatusPill tone={i.status === "Planned" ? "info" : "neutral"}>{i.status}</StatusPill>
                  <Button size="sm" variant="outline" onClick={() => toast.info(`Connect ${i.name} (mock)`)}>Connect</Button>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="surface-card p-6">
          <h3 className="font-display text-lg font-semibold mb-4 flex items-center gap-2"><KeyRound className="h-5 w-5 text-primary" />Roles & permissions</h3>
          <div className="space-y-2">
            {[
              { role: "Director", who: "Prarit Sidana", scope: "All" },
              { role: "Operations Manager", who: "—", scope: "Orders, Delivery, RTO" },
              { role: "Calling TL", who: "—", scope: "Calling, Confirmation" },
              { role: "Compliance Officer", who: "—", scope: "Claim Vault, CAIO" },
              { role: "Finance", who: "—", scope: "Payments, Net Profit" },
            ].map((r) => (
              <div key={r.role} className="flex items-center justify-between rounded-xl bg-muted/40 p-3">
                <div>
                  <div className="font-medium">{r.role}</div>
                  <div className="text-xs text-muted-foreground">{r.who}</div>
                </div>
                <StatusPill tone="info">{r.scope}</StatusPill>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="surface-card p-6">
        <h3 className="font-display text-lg font-semibold mb-3 flex items-center gap-2"><ScrollText className="h-5 w-5 text-primary" />Master Event Ledger</h3>
        <p className="text-sm text-muted-foreground mb-3">Immutable record of every AI decision, business event and approval.</p>
        <div className="font-mono text-xs bg-foreground text-background p-4 rounded-xl space-y-1 max-h-56 overflow-auto scrollbar-thin">
          <div>10:42:18  CEO_AI  approve  rec=rec-3  user=auto</div>
          <div>10:41:55  CALLING_AI  order_punched  order=NRG-20431</div>
          <div>10:41:02  COMPLIANCE  block  claim="permanent solution"</div>
          <div>10:40:11  RTO_AGENT  rescue_call  order=NRG-20418  result=convinced</div>
          <div>10:39:47  RAZORPAY  payment_received  amount=499  order=NRG-20431</div>
          <div>10:38:22  CAIO  flag  agent=Sales_Growth  severity=High</div>
        </div>
      </div>
    </>
  );
}

function ControlCard({ icon: Icon, title, desc, tone, children }: any) {
  const ring: any = { danger: "border-l-destructive", info: "border-l-info", warning: "border-l-warning" };
  return (
    <div className={`surface-card p-5 border-l-4 ${ring[tone]}`}>
      <div className="flex items-center justify-between mb-2">
        <Icon className={`h-5 w-5 text-${tone === "danger" ? "destructive" : tone}`} />
        {children}
      </div>
      <div className="font-display text-lg font-semibold">{title}</div>
      <div className="text-xs text-muted-foreground">{desc}</div>
    </div>
  );
}

interface WabaStatFieldProps {
  label: string;
  value: string;
  tone: "success" | "warning" | "info" | "neutral";
}

function WabaStatField({ label, value, tone }: WabaStatFieldProps) {
  return (
    <div className="rounded-xl bg-muted/40 px-3 py-3">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-1">
        {label}
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium truncate">{value}</span>
        <StatusPill tone={tone}>{tone}</StatusPill>
      </div>
    </div>
  );
}