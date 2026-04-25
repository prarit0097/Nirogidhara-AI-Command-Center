import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import * as M from "@/services/mockData";
import { ShieldCheck, ShieldAlert, Stethoscope, FileBadge2 } from "lucide-react";

const RED_FLAGS = ["Guaranteed cure", "Permanent solution", "No side effects for everyone", "Emergency medical advice", "Works for everyone universally", "Doctor ki zarurat nahi"];

export default function Claims() {
  return (
    <>
      <PageHeader eyebrow="Governance" title="Claim Vault & Compliance"
        description="Doctor & compliance approved claims for every product. AI can only speak from this Vault."
      />

      <div className="surface-elevated p-6 mb-6 bg-gradient-emerald-soft border-l-4 border-l-success">
        <div className="flex items-start gap-3">
          <ShieldCheck className="h-6 w-6 text-success mt-1" />
          <div>
            <h3 className="font-display text-lg font-semibold">Approved claim only.</h3>
            <p className="text-sm text-muted-foreground mt-1 max-w-3xl">
              AI can only speak from <strong>doctor-approved and compliance-approved Claim Vault content</strong>. Any drafted claim outside the vault is auto-blocked and routed for review.
            </p>
          </div>
        </div>
      </div>

      <div className="surface-card p-6 mb-6">
        <h3 className="font-display text-lg font-semibold mb-3 flex items-center gap-2"><ShieldAlert className="h-5 w-5 text-destructive" />Red-flag detector</h3>
        <p className="text-sm text-muted-foreground mb-3">Any draft using these phrases is auto-blocked.</p>
        <div className="flex flex-wrap gap-1.5">
          {RED_FLAGS.map((r) => <StatusPill key={r} tone="danger">{r}</StatusPill>)}
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        {M.CLAIM_VAULT.map((c) => (
          <div key={c.product} className="surface-card p-6">
            <div className="flex items-start justify-between mb-3">
              <div>
                <h3 className="font-display text-lg font-semibold">{c.product}</h3>
                <div className="text-xs text-muted-foreground font-mono">{c.version}</div>
              </div>
              <div className="flex flex-col gap-1.5 items-end">
                <StatusPill tone={c.doctor === "Approved" ? "success" : "warning"} icon={<Stethoscope className="h-3 w-3" />}>Doctor: {c.doctor}</StatusPill>
                <StatusPill tone={c.compliance === "Approved" ? "success" : "warning"} icon={<FileBadge2 className="h-3 w-3" />}>Compliance: {c.compliance}</StatusPill>
              </div>
            </div>
            <div className="rounded-xl bg-success/10 border border-success/20 p-3 mb-3">
              <div className="text-xs uppercase tracking-wider text-success font-semibold mb-1.5">Approved claims</div>
              <ul className="space-y-1 text-sm">
                {c.approved.map((a) => <li key={a}>✓ {a}</li>)}
              </ul>
            </div>
            <div className="rounded-xl bg-destructive/10 border border-destructive/20 p-3">
              <div className="text-xs uppercase tracking-wider text-destructive font-semibold mb-1.5">Disallowed</div>
              <ul className="space-y-1 text-sm">
                {c.disallowed.map((a) => <li key={a}>✗ {a}</li>)}
              </ul>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}