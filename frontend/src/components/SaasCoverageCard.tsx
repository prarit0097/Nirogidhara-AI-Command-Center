import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Building2,
  CheckCircle2,
  Database,
  Lock,
} from "lucide-react";
import { api } from "@/services/api";
import type { SaasDataCoverage } from "@/types/domain";

/**
 * Phase 6B — read-only SaaS data-coverage card.
 *
 * Surfaces the default-org backfill state (org/branch coverage
 * percentages, missing-row counts, backend nextAction) on the dashboard.
 * There are NO backfill / migrate / mutation buttons on this card —
 * those run as management commands on the VPS.
 */
export function SaasCoverageCard() {
  const [coverage, setCoverage] = useState<SaasDataCoverage | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getSaasDataCoverage()
      .then((res) => {
        if (cancelled) return;
        setCoverage(res);
      })
      .catch(() => {
        if (cancelled) return;
        setCoverage(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!coverage) {
    return null;
  }

  const orgPct = coverage.totals.organizationCoveragePercent;
  const branchPct = coverage.totals.branchCoveragePercent;
  const allClean =
    coverage.totals.totalWithoutOrganization === 0 &&
    coverage.totals.totalWithoutBranch === 0;

  return (
    <div className="surface-card p-5" data-testid="saas-coverage-card">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div className="flex items-center gap-2">
          <Database className="h-4 w-4 text-muted-foreground" />
          <h3 className="text-sm font-semibold uppercase tracking-wide">
            SaaS data coverage
          </h3>
        </div>
        <span
          className={`inline-flex items-center gap-1.5 text-xs font-medium ${
            allClean ? "text-success" : "text-warning"
          }`}
        >
          {allClean ? (
            <>
              <CheckCircle2 className="h-3.5 w-3.5" />
              Backfill complete
            </>
          ) : (
            <>
              <AlertTriangle className="h-3.5 w-3.5" />
              Backfill pending
            </>
          )}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 mb-4">
        <div>
          <div className="text-xs text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
            <Building2 className="h-3.5 w-3.5" />
            Default org
          </div>
          <div className="font-medium mt-0.5 truncate">
            {coverage.defaultOrganizationCode}
          </div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
            <Lock className="h-3.5 w-3.5" />
            Tenant filtering
          </div>
          <div className="font-medium mt-0.5">
            {coverage.globalTenantFilteringEnabled ? "Enabled" : "Off (Phase 6C)"}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 mb-4">
        <div>
          <div className="text-xs text-muted-foreground uppercase tracking-wide">
            Organization coverage
          </div>
          <div
            className={`text-2xl font-semibold mt-0.5 ${
              orgPct >= 100 ? "text-success" : "text-warning"
            }`}
          >
            {orgPct.toFixed(2)}%
          </div>
          <div className="text-xs text-muted-foreground mt-0.5">
            {coverage.totals.totalWithOrganization} /{" "}
            {coverage.totals.totalRows} rows
          </div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground uppercase tracking-wide">
            Branch coverage
          </div>
          <div
            className={`text-2xl font-semibold mt-0.5 ${
              branchPct >= 100 ? "text-success" : "text-warning"
            }`}
          >
            {branchPct.toFixed(2)}%
          </div>
          <div className="text-xs text-muted-foreground mt-0.5">
            branch-eligible models
          </div>
        </div>
      </div>

      {coverage.totals.totalWithoutOrganization > 0 && (
        <div className="text-xs text-warning mb-2">
          {coverage.totals.totalWithoutOrganization} row(s) still missing
          organization.
        </div>
      )}
      {coverage.totals.totalWithoutBranch > 0 && (
        <div className="text-xs text-warning mb-2">
          {coverage.totals.totalWithoutBranch} row(s) still missing branch.
        </div>
      )}

      <div className="text-xs text-muted-foreground border-t border-border/60 pt-3 font-mono break-all">
        {coverage.nextAction || "—"}
      </div>
    </div>
  );
}
