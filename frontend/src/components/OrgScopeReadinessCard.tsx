import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Filter,
  Lock,
  ShieldCheck,
} from "lucide-react";
import { api } from "@/services/api";
import type { SaasOrgScopeReadiness } from "@/types/domain";

/**
 * Phase 6C — read-only org-scope readiness card.
 *
 * Surfaces the Phase 6C foundation state on the dashboard:
 * default org / branch presence, org + branch coverage %,
 * audit auto-org context, scoped vs unscoped model + API counts,
 * and the backend-computed nextAction. There are NO mutation
 * controls (no org-switch, no enable/disable, no migrate buttons).
 */
export function OrgScopeReadinessCard() {
  const [readiness, setReadiness] = useState<SaasOrgScopeReadiness | null>(
    null,
  );

  useEffect(() => {
    let cancelled = false;
    api
      .getSaasOrgScopeReadiness()
      .then((res) => {
        if (cancelled) return;
        setReadiness(res);
      })
      .catch(() => {
        if (cancelled) return;
        setReadiness(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!readiness) {
    return null;
  }

  return (
    <div className="surface-card p-5" data-testid="org-scope-readiness-card">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-muted-foreground" />
          <h3 className="text-sm font-semibold uppercase tracking-wide">
            Org-scope readiness
          </h3>
        </div>
        <span
          className={`inline-flex items-center gap-1.5 text-xs font-medium ${
            readiness.safeToStartPhase6D ? "text-success" : "text-warning"
          }`}
        >
          {readiness.safeToStartPhase6D ? (
            <>
              <CheckCircle2 className="h-3.5 w-3.5" />
              Phase 6D ready
            </>
          ) : (
            <>
              <AlertTriangle className="h-3.5 w-3.5" />
              Pending
            </>
          )}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 mb-4">
        <div>
          <div className="text-xs text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
            <ShieldCheck className="h-3.5 w-3.5" />
            Audit auto-org
          </div>
          <div
            className={`font-medium mt-0.5 ${
              readiness.auditAutoOrgContextEnabled
                ? "text-success"
                : "text-warning"
            }`}
          >
            {readiness.auditAutoOrgContextEnabled ? "Enabled" : "Off"}
          </div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
            <Lock className="h-3.5 w-3.5" />
            Global filter
          </div>
          <div className="font-medium mt-0.5">
            {readiness.globalTenantFilteringEnabled
              ? "Enabled"
              : "Off (Phase 6E)"}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 mb-4">
        <div>
          <div className="text-xs text-muted-foreground uppercase tracking-wide">
            Scoped models / APIs
          </div>
          <div className="text-2xl font-semibold mt-0.5 text-success">
            {readiness.scopedModels.length} / {readiness.scopedApis.length}
          </div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground uppercase tracking-wide">
            Unscoped models / APIs
          </div>
          <div className="text-2xl font-semibold mt-0.5 text-muted-foreground">
            {readiness.unscopedModels.length} /{" "}
            {readiness.unscopedApis.length}
          </div>
        </div>
      </div>

      {readiness.warnings.length > 0 && (
        <ul className="text-xs text-warning mb-2 space-y-1">
          {readiness.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      {readiness.blockers.length > 0 && (
        <ul className="text-xs text-destructive mb-2 space-y-1">
          {readiness.blockers.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      )}

      <div className="text-xs text-muted-foreground border-t border-border/60 pt-3 font-mono break-all">
        {readiness.nextAction || "—"}
      </div>
    </div>
  );
}
