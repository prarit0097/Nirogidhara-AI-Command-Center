/**
 * Phase 15H - Topbar Safety Sync indicator helper.
 *
 * Maps the WebSocket lifecycle exposed by the SafetyStateProvider
 * into a compact label + accessible tooltip + Tailwind class for
 * the read-only Topbar pill.
 *
 * Pure helper - no React, no fetches, no DOM. The Topbar passes
 * the current `safetySyncStatus` (and optionally a timestamp) and
 * gets a ready-to-render record back.
 */
import type { SafetySyncStatus } from "@/context/SafetyStateContext";

export type SafetySyncIndicatorTone =
  | "success"
  | "info"
  | "warning"
  | "neutral";

export interface SafetySyncIndicatorVisual {
  /** Full pill label - rendered at xl+ widths. Begins with "Sync:". */
  label: string;
  /** Compact label - rendered below xl. No "Sync:" prefix. */
  compactLabel: string;
  /** Semantic tone the pill maps to a colour class. */
  tone: SafetySyncIndicatorTone;
  /** Tailwind classes for border + bg + text colour. */
  className: string;
  /** Long-form aria-label / title. Always ends "Read-only indicator." */
  tooltip: string;
  /**
   * Short token surfaced via `data-safety-sync-status` so e2e and
   * regression tests can assert without depending on label text.
   */
  dataStatus: SafetySyncStatus;
}

const TONE_CLASS: Record<SafetySyncIndicatorTone, string> = {
  success:
    "border-success/30 bg-success/10 text-success",
  info:
    "border-info/30 bg-info/10 text-info",
  warning:
    "border-warning/40 bg-warning/10 text-warning",
  neutral:
    "border-border bg-muted/40 text-muted-foreground",
};

export function computeSafetySyncIndicator(
  status: SafetySyncStatus,
): SafetySyncIndicatorVisual {
  switch (status) {
    case "live":
      return {
        label: "Sync: Live",
        compactLabel: "Live",
        tone: "success",
        className: TONE_CLASS.success,
        tooltip:
          "Safety Sync: Live - audit event stream connected. Read-only indicator.",
        dataStatus: status,
      };
    case "connecting":
      return {
        label: "Sync: Connecting",
        compactLabel: "Connect",
        tone: "info",
        className: TONE_CLASS.info,
        tooltip:
          "Safety Sync: Connecting - opening audit event stream; using last fetched safety state until live. Read-only indicator.",
        dataStatus: status,
      };
    case "reconnecting":
      return {
        label: "Sync: Reconnecting",
        compactLabel: "Reconnect",
        tone: "warning",
        className: TONE_CLASS.warning,
        tooltip:
          "Safety Sync: Reconnecting - safety state will continue using last known status while the stream reconnects. Read-only indicator.",
        dataStatus: status,
      };
    case "offline":
      return {
        label: "Sync: Offline",
        compactLabel: "Offline",
        tone: "warning",
        className: TONE_CLASS.warning,
        tooltip:
          "Safety Sync: Offline - page still shows last fetched safety status; refresh page if needed. Read-only indicator.",
        dataStatus: status,
      };
    case "unavailable":
    default:
      return {
        label: "Sync: Unavailable",
        compactLabel: "Unavail",
        tone: "neutral",
        className: TONE_CLASS.neutral,
        tooltip:
          "Safety Sync: Unavailable - audit event stream cannot start; chrome continues using GET-fetched safety status. Read-only indicator.",
        dataStatus: status,
      };
  }
}

export const __testing__ = {
  TONE_CLASS,
};
