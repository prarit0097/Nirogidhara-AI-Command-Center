/**
 * Phase 15J - Safety Diagnostics Detail Drawer/Modal.
 *
 * Read-only deep-dive surface launched from the Phase 15I
 * SafetyDiagnosticsPanel's "View details" button. Renders a
 * sanitised view of safety sync lifecycle + endpoint health +
 * derived error labels.
 *
 * Hard guarantees:
 *   - NEVER calls any backend method. Open/close is local state
 *     only.
 *   - NEVER renders raw payloads, tokens, secrets, full phones,
 *     emails, addresses, prompt bodies, provider payloads, or
 *     raw audit payloads. Only enums + locale ISO + short sanitised
 *     labels surface.
 *   - NEVER mutates RuntimeKillSwitch / SandboxState / PromptVersion /
 *     business tables.
 *   - The footer carries a literal "This drawer is read-only ..."
 *     sentence so a screen-reader user and code reviewers see the
 *     contract verbatim.
 */
import { RefreshCw } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/StatusPill";
import { cn } from "@/lib/utils";
import {
  useSafetyState,
  type SafetyEndpointStatus,
  type SafetyRefreshSource,
  type SafetySyncStatus,
} from "@/context/SafetyStateContext";

export interface SafetyDiagnosticsDetailModalProps {
  open: boolean;
  onOpenChange: (next: boolean) => void;
}

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

/**
 * Derive the refresh-source label from existing useSafetyState
 * fields without adding new context tracking:
 *   - Refresh + event both present + refresh >= event -> audit_event
 *   - Refresh present + event absent                  -> initial_load
 *   - Neither present                                 -> unknown
 *   - Event present but no refresh yet                -> unknown (the
 *     refresh hasn't landed yet but an event did fire)
 */
export function deriveRefreshSourceLabel(
  lastSafetyRefreshAt: string | null,
  lastSafetyEventAt: string | null,
): "initial_load" | "audit_event" | "unknown" {
  if (lastSafetyRefreshAt && lastSafetyEventAt) {
    try {
      const r = new Date(lastSafetyRefreshAt).getTime();
      const e = new Date(lastSafetyEventAt).getTime();
      if (!Number.isFinite(r) || !Number.isFinite(e)) return "unknown";
      return r >= e ? "audit_event" : "unknown";
    } catch {
      return "unknown";
    }
  }
  if (lastSafetyRefreshAt && !lastSafetyEventAt) return "initial_load";
  return "unknown";
}

function refreshSourceLabel(source: SafetyRefreshSource): string {
  switch (source) {
    case "initial_load":
      return "Initial load";
    case "audit_event":
      return "Audit event";
    case "manual_refresh":
      return "Manual refresh";
    case "unknown":
    default:
      return "Unknown";
  }
}

/**
 * Compose the sanitised error summary list. Returns short labels
 * only — never raw error messages, stack traces, or response
 * bodies.
 */
export function buildErrorSummary(input: {
  killSwitchStatus: SafetyEndpointStatus;
  sandboxStatus: SafetyEndpointStatus;
  briefingStatus: SafetyEndpointStatus;
  safetySyncStatus: SafetySyncStatus;
}): string[] {
  const out: string[] = [];
  if (input.killSwitchStatus === "error") {
    out.push("Kill switch endpoint failed");
  }
  if (input.sandboxStatus === "error") {
    out.push("Sandbox endpoint failed");
  }
  if (input.briefingStatus === "error") {
    out.push("Briefing endpoint failed");
  }
  if (
    input.safetySyncStatus === "offline" ||
    input.safetySyncStatus === "unavailable"
  ) {
    out.push("Safety sync stream unavailable");
  }
  return out;
}

interface DetailRowProps {
  label: string;
  testid: string;
  value: string;
  tone?: "success" | "info" | "warning" | "neutral";
  asPill?: boolean;
}

function DetailRow({ label, testid, value, tone, asPill }: DetailRowProps) {
  return (
    <div
      data-testid={testid}
      className="flex items-center justify-between gap-4 py-1.5"
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

export function SafetyDiagnosticsDetailModal({
  open,
  onOpenChange,
}: SafetyDiagnosticsDetailModalProps) {
  const {
    safetySyncStatus,
    lastSafetyEventAt,
    lastSafetyRefreshAt,
    killSwitchStatus,
    sandboxStatus,
    briefingStatus,
    // Phase 15L — real refresh source + manual-refresh trigger.
    lastRefreshSource,
    refreshing,
    refreshSafetyState,
  } = useSafetyState();

  const sync = syncVisual(safetySyncStatus);
  const ks = endpointVisual(killSwitchStatus);
  const sb = endpointVisual(sandboxStatus);
  const br = endpointVisual(briefingStatus);
  // Phase 15L — prefer the provider's `lastRefreshSource` field
  // (set explicitly inside fetchAll). Fall back to the Phase 15J
  // timestamp heuristic when the provider has no source yet
  // (e.g. the inert hook-outside-provider snapshot).
  const refreshSource: SafetyRefreshSource =
    lastRefreshSource !== "unknown"
      ? lastRefreshSource
      : deriveRefreshSourceLabel(lastSafetyRefreshAt, lastSafetyEventAt);
  const errors = buildErrorSummary({
    killSwitchStatus,
    sandboxStatus,
    briefingStatus,
    safetySyncStatus,
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="safety-diagnostics-detail-modal"
        className="max-w-lg"
      >
        <DialogHeader>
          <DialogTitle data-testid="safety-diagnostics-detail-title">
            Safety Diagnostics Details
          </DialogTitle>
          <DialogDescription>
            Read-only technical visibility for safety sync and endpoint health.
          </DialogDescription>
        </DialogHeader>

        <section
          data-testid="safety-diagnostics-detail-sync-section"
          className="rounded-lg border border-border/60 px-4 py-3"
        >
          <h4 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
            Safety sync
          </h4>
          <DetailRow
            label="Status"
            testid="detail-sync-status"
            value={sync.label}
            tone={sync.tone}
            asPill
          />
          <DetailRow
            label="Last audit event"
            testid="detail-last-event"
            value={formatTimestamp(lastSafetyEventAt, "No event seen yet")}
          />
          <DetailRow
            label="Last safety refresh"
            testid="detail-last-refresh"
            value={formatTimestamp(lastSafetyRefreshAt, "Never")}
          />
          <DetailRow
            label="Refresh source"
            testid="detail-refresh-source"
            value={refreshSourceLabel(refreshSource)}
          />
          <DetailRow
            label="Reconnect attempts"
            testid="detail-reconnect-attempts"
            value="Not tracked"
          />
        </section>

        <section
          data-testid="safety-diagnostics-detail-endpoints-section"
          className="rounded-lg border border-border/60 px-4 py-3"
        >
          <h4 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
            Endpoint health
          </h4>
          <DetailRow
            label="Kill switch endpoint"
            testid="detail-kill-switch"
            value={ks.label}
            tone={ks.tone}
            asPill
          />
          <DetailRow
            label="Sandbox endpoint"
            testid="detail-sandbox"
            value={sb.label}
            tone={sb.tone}
            asPill
          />
          <DetailRow
            label="Briefing status endpoint"
            testid="detail-briefing"
            value={br.label}
            tone={br.tone}
            asPill
          />
        </section>

        <section
          data-testid="safety-diagnostics-detail-errors-section"
          className="rounded-lg border border-border/60 px-4 py-3"
        >
          <h4 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
            Safe error summary
          </h4>
          {errors.length === 0 ? (
            <p
              data-testid="detail-errors-empty"
              className="text-[12.5px] text-muted-foreground"
            >
              No safety errors detected.
            </p>
          ) : (
            <ul
              data-testid="detail-errors-list"
              className="text-[12.5px] text-warning space-y-1"
            >
              {errors.map((label) => (
                <li
                  key={label}
                  data-testid={`detail-error-${label
                    .toLowerCase()
                    .replace(/\s+/g, "-")}`}
                >
                  {label}
                </li>
              ))}
            </ul>
          )}
        </section>

        <p
          data-testid="safety-diagnostics-detail-readonly-note"
          className="text-[11.5px] text-muted-foreground italic"
        >
          This drawer is read-only. It does not resume AI, toggle sandbox,
          rollback prompts, send messages, call customers, create audit
          events, or change business data.
        </p>

        <DialogFooter className="gap-2 sm:gap-2">
          {/* Phase 15L — read-only "Refresh status" inside the
              detail drawer. Reuses the shared refreshSafetyState
              callback; never mutates safety or business state. */}
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              void refreshSafetyState();
            }}
            disabled={refreshing}
            data-testid="safety-diagnostics-detail-refresh"
            aria-label={
              refreshing
                ? "Refreshing Safety Diagnostics"
                : "Refresh Safety Diagnostics status"
            }
          >
            <RefreshCw
              className={cn(
                "h-3.5 w-3.5",
                refreshing && "animate-spin",
              )}
              aria-hidden
            />
            <span
              data-testid="safety-diagnostics-detail-refresh-label"
              className="ml-1.5"
            >
              {refreshing ? "Refreshing…" : "Refresh status"}
            </span>
          </Button>
          <Button
            type="button"
            variant="secondary"
            onClick={() => onOpenChange(false)}
            data-testid="safety-diagnostics-detail-close"
            aria-label="Close Safety Diagnostics Details"
          >
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export const __testing__ = {
  syncVisual,
  endpointVisual,
  deriveRefreshSourceLabel,
  refreshSourceLabel,
  buildErrorSummary,
  formatTimestamp,
};
