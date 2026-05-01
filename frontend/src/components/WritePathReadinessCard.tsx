import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  Lock,
  PenSquare,
  ShieldCheck,
} from "lucide-react";
import { api } from "@/services/api";
import type { SaasWritePathReadiness } from "@/types/domain";

/**
 * Phase 6D — read-only write-path readiness card.
 *
 * Shows the auto-assign signal coverage, recent missing-org row counts,
 * deferred paths, and the backend nextAction. There are NO mutation
 * controls (no run-backfill / run-migrate / org-switch buttons).
 */
export function WritePathReadinessCard() {
  const [readiness, setReadiness] =
    useState<SaasWritePathReadiness | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getSaasWritePathReadiness()
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

  const missingTotal =
    readiness.recentRowsWithoutOrganizationLast24h +
    readiness.recentRowsWithoutBranchLast24h;
  const allClean = missingTotal === 0;

  return (
    <div className="surface-card p-5" data-testid="write-path-readiness-card">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div className="flex items-center gap-2">
          <PenSquare className="h-4 w-4 text-muted-foreground" />
          <h3 className="text-sm font-semibold uppercase tracking-wide">
            Write-path readiness
          </h3>
        </div>
        <span
          className={`inline-flex items-center gap-1.5 text-xs font-medium ${
            readiness.safeToStartPhase6E ? "text-success" : "text-warning"
          }`}
        >
          {readiness.safeToStartPhase6E ? (
            <>
              <CheckCircle2 className="h-3.5 w-3.5" />
              Phase 6E ready
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
            Auto-assign signal
          </div>
          <div
            className={`font-medium mt-0.5 ${
              readiness.writeContextHelpersAvailable
                ? "text-success"
                : "text-warning"
            }`}
          >
            {readiness.writeContextHelpersAvailable ? "Wired" : "Off"}
          </div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
            <Lock className="h-3.5 w-3.5" />
            Global enforcement
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
            Covered create paths
          </div>
          <div className="text-2xl font-semibold mt-0.5 text-success">
            {readiness.safeCreatePathsCovered.length}
          </div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground uppercase tracking-wide">
            Deferred (Phase 6E)
          </div>
          <div className="text-2xl font-semibold mt-0.5 text-muted-foreground">
            {readiness.deferredCreatePaths.length}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 mb-4">
        <div>
          <div className="text-xs text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
            <Database className="h-3.5 w-3.5" />
            Missing org · 24h
          </div>
          <div
            className={`text-2xl font-semibold mt-0.5 ${
              readiness.recentRowsWithoutOrganizationLast24h === 0
                ? "text-success"
                : "text-warning"
            }`}
          >
            {readiness.recentRowsWithoutOrganizationLast24h}
          </div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
            <Database className="h-3.5 w-3.5" />
            Missing branch · 24h
          </div>
          <div
            className={`text-2xl font-semibold mt-0.5 ${
              readiness.recentRowsWithoutBranchLast24h === 0
                ? "text-success"
                : "text-warning"
            }`}
          >
            {readiness.recentRowsWithoutBranchLast24h}
          </div>
        </div>
      </div>

      {!allClean && (
        <div className="text-xs text-warning mb-2">
          Run backfill_default_organization_data --apply to scope the
          recent NULL rows.
        </div>
      )}
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
