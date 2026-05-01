import { useEffect, useState } from "react";
import { Building2 } from "lucide-react";
import { api } from "@/services/api";
import type { SaasOrganization } from "@/types/domain";

/**
 * Phase 6A — read-only Organization badge.
 *
 * Renders the user's current organization name in the topbar. There are
 * NO switching, enable, or pause controls in this phase — those land in
 * Phase 6E (SaaS admin panel). The badge falls back to the deterministic
 * mock when the backend is offline so the page never crashes.
 */
export function OrgBadge() {
  const [org, setOrg] = useState<SaasOrganization | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getSaasCurrentOrganization()
      .then((res) => {
        if (cancelled) return;
        setOrg(res.organization);
      })
      .catch(() => {
        if (cancelled) return;
        setOrg(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!org) {
    return null;
  }

  return (
    <div
      className="hidden lg:flex items-center gap-1.5 px-3 h-9 rounded-full bg-muted/40 border border-border/60 text-xs text-muted-foreground"
      data-testid="org-badge"
      title={`Organization: ${org.name}`}
    >
      <Building2 className="h-3.5 w-3.5" />
      <span className="font-medium text-foreground truncate max-w-[180px]">
        {org.name}
      </span>
      {org.userOrgRole && (
        <span className="uppercase tracking-wider text-[10px]">
          {org.userOrgRole}
        </span>
      )}
    </div>
  );
}
