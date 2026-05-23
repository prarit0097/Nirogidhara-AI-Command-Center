/**
 * Phase 15I - Safety Diagnostics Mini Panel.
 *
 * Read-only diagnostics for the Settings & Control page. Consumes
 * the shared SafetyStateProvider (Phase 15F) and surfaces the
 * lifecycle / endpoint health fields added by Phase 15G/15H/15I.
 *
 * Hard rules:
 *   - No fetches of its own; consumes useSafetyState() only.
 *   - No mutation. No POST/PATCH/DELETE.
 *   - No action buttons (no "Refresh diagnostics" in this phase -
 *     keeps the panel strictly passive).
 *   - No raw payloads, tokens, secrets, full phones, or PII -
 *     panel renders only enum statuses + ISO->locale timestamps.
 */
import { useState } from "react";
import { Activity, ShieldCheck } from "lucide-react";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import {
  useSafetyState,
  type SafetyEndpointStatus,
  type SafetySyncStatus,
} from "@/context/SafetyStateContext";
import { SafetyDiagnosticsDetailModal } from "@/components/settings/SafetyDiagnosticsDetailModal";

function formatTimestamp(iso: string | null, emptyLabel: string): string {
  if (!iso) return emptyLabel;
  try {
    const dt = new Date(iso);
    if (Number.isNaN(dt.getTime())) return emptyLabel;
    return dt.toLocaleString();
  } catch {
    return emptyLabel;
  }
}

interface SyncVisual {
  label: string;
  tone: "success" | "info" | "warning" | "neutral";
}

function syncVisual(status: SafetySyncStatus): SyncVisual {
  switch (status) {
    case "live":
      return { label: "Live", tone: "success" };
    case "connecting":
      return { label: "Connecting", tone: "info" };
    case "reconnecting":
      return { label: "Reconnecting", tone: "warning" };
    case "offline":
      return { label: "Offline", tone: "warning" };
    case "unavailable":
    default:
      return { label: "Unavailable", tone: "neutral" };
  }
}

interface EndpointVisual {
  label: string;
  tone: "success" | "info" | "warning";
}

function endpointVisual(status: SafetyEndpointStatus): EndpointVisual {
  switch (status) {
    case "ok":
      return { label: "OK", tone: "success" };
    case "loading":
      return { label: "Loading", tone: "info" };
    case "error":
    default:
      return { label: "Error", tone: "warning" };
  }
}

interface DiagnosticsRowProps {
  label: string;
  testid: string;
  value: string;
  tone?: "success" | "info" | "warning" | "neutral";
  asPill?: boolean;
}

function DiagnosticsRow({
  label,
  testid,
  value,
  tone,
  asPill,
}: DiagnosticsRowProps) {
  return (
    <div
      data-testid={testid}
      className="flex items-center justify-between gap-4 py-2 border-b border-border/40 last:border-b-0"
    >
      <span className="text-[12.5px] text-muted-foreground">{label}</span>
      <span data-testid={`${testid}-value`} className="text-[12.5px]">
        {asPill ? (
          <StatusPill tone={tone ?? "neutral"}>{value}</StatusPill>
        ) : (
          <span className="font-mono text-foreground/85">{value}</span>
        )}
      </span>
    </div>
  );
}

export function SafetyDiagnosticsPanel() {
  const {
    safetySyncStatus,
    lastSafetyEventAt,
    lastSafetyRefreshAt,
    killSwitchStatus,
    sandboxStatus,
    briefingStatus,
  } = useSafetyState();

  // Phase 15J — local-only modal state for the read-only details
  // drawer. The button is the only mutation of any UI state in this
  // component; nothing crosses the backend boundary.
  const [detailOpen, setDetailOpen] = useState<boolean>(false);

  const sync = syncVisual(safetySyncStatus);
  const ks = endpointVisual(killSwitchStatus);
  const sb = endpointVisual(sandboxStatus);
  const br = endpointVisual(briefingStatus);

  return (
    <section
      data-testid="safety-diagnostics-panel"
      className="surface-card overflow-hidden mb-6"
    >
      <div className="px-6 py-4 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-5 w-5 text-primary" />
          <div>
            <h3 className="font-display text-lg font-semibold">
              Safety Diagnostics
            </h3>
            <p className="text-[11.5px] text-muted-foreground">
              Read-only live safety sync and endpoint health.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {/* Phase 15J — read-only "View details" trigger. Opens a
              local modal; never calls the backend. */}
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="safety-diagnostics-view-details"
            onClick={() => setDetailOpen(true)}
            aria-label="View Safety Diagnostics details"
          >
            View details
          </Button>
          <Activity
            className="h-4 w-4 text-muted-foreground"
            aria-hidden
          />
        </div>
      </div>
      <div className="px-6 py-3">
        <DiagnosticsRow
          label="Safety sync"
          testid="diagnostics-safety-sync"
          value={sync.label}
          tone={sync.tone}
          asPill
        />
        <DiagnosticsRow
          label="Last safety refresh"
          testid="diagnostics-last-refresh"
          value={formatTimestamp(lastSafetyRefreshAt, "Never")}
        />
        <DiagnosticsRow
          label="Last audit event"
          testid="diagnostics-last-event"
          value={formatTimestamp(lastSafetyEventAt, "No event seen yet")}
        />
        <DiagnosticsRow
          label="Kill switch endpoint"
          testid="diagnostics-kill-switch"
          value={ks.label}
          tone={ks.tone}
          asPill
        />
        <DiagnosticsRow
          label="Sandbox endpoint"
          testid="diagnostics-sandbox"
          value={sb.label}
          tone={sb.tone}
          asPill
        />
        <DiagnosticsRow
          label="Briefing status endpoint"
          testid="diagnostics-briefing"
          value={br.label}
          tone={br.tone}
          asPill
        />
      </div>

      {/* Phase 15J - Safety Diagnostics Detail Drawer. Read-only,
          local-only state, never calls backend. */}
      <SafetyDiagnosticsDetailModal
        open={detailOpen}
        onOpenChange={(next) => setDetailOpen(next)}
      />
    </section>
  );
}

export const __testing__ = {
  syncVisual,
  endpointVisual,
  formatTimestamp,
};
