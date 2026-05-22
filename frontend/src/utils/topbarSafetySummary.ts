/**
 * Phase 15D - Topbar Safety Compact Pill helper.
 *
 * Composes the kill-switch (Phase 14D), sandbox (Phase 14E), and
 * Director Briefing (Phase 15B) statuses into a single compact
 * label + tone + tooltip for the Topbar pill.
 *
 * Pure helper - no fetches, no React deps. Callers pass the
 * snapshots they already fetched plus per-source error flags.
 *
 * Priority (highest visual weight first):
 *   1. Loading - any fetch still in flight + no error.
 *   2. Kill switch paused / AI blocked - amber/warning.
 *   3. Sandbox ON - blue/info.
 *   4. Briefing critical - red/danger.
 *   5. Briefing stale or any fetch unavailable - amber/warning.
 *   6. All normal - green/success.
 *
 * The pill NEVER asserts all-normal when any required fetch errored.
 * It NEVER triggers any action. It is read-only display.
 */
import type {
  AiSandboxModeStatus,
  DirectorBriefingSidebarStatus,
  SaasRuntimeLiveGateKillSwitch,
} from "@/types/domain";

export type TopbarSafetyTone =
  | "success"
  | "info"
  | "warning"
  | "danger"
  | "neutral";

export interface TopbarSafetySummary {
  /** Full pill label. Always begins with "Safety:". Rendered at xl+. */
  label: string;
  /**
   * Compact pill label for medium widths (md/lg). Drops the
   * "Safety:" prefix and abbreviates Sandbox -> SBOX and the
   * Briefing token -> bare status. Always non-empty so the medium
   * breakpoint never goes blank.
   */
  compactLabel: string;
  /** Semantic tone - the pill maps this to a colour class. */
  tone: TopbarSafetyTone;
  /** Tailwind background class for the pill body. */
  className: string;
  /**
   * Long-form accessible tooltip / aria-label. Lists each upstream
   * signal so a screen reader user gets the whole picture.
   */
  tooltip: string;
  /** Short token surfaced via `data-safety-status` for e2e tests. */
  dataStatus:
    | "loading"
    | "ai_paused"
    | "ai_running"
    | "unavailable";
}

export interface TopbarSafetySummaryInputs {
  killSwitch: SaasRuntimeLiveGateKillSwitch | null;
  sandbox: AiSandboxModeStatus | null;
  briefing: DirectorBriefingSidebarStatus | null;
  killSwitchError?: boolean;
  sandboxError?: boolean;
  briefingError?: boolean;
}

const TONE_CLASS: Record<TopbarSafetyTone, string> = {
  success:
    "border-success/30 bg-success/10 text-success",
  info:
    "border-info/30 bg-info/10 text-info",
  warning:
    "border-warning/40 bg-warning/10 text-warning",
  danger:
    "border-destructive/40 bg-destructive/10 text-destructive",
  neutral:
    "border-border bg-muted/40 text-muted-foreground",
};

function describeKillSwitch(
  killSwitch: SaasRuntimeLiveGateKillSwitch | null,
  errored: boolean,
): { compact: string; long: string; paused: boolean | null } {
  if (errored) {
    return { compact: "AI ?", long: "Kill Switch: unavailable", paused: null };
  }
  if (killSwitch === null) {
    return { compact: "AI ?", long: "Kill Switch: loading", paused: null };
  }
  const paused = Boolean(
    killSwitch.aiExecutionBlocked ?? killSwitch.enabled ?? false,
  );
  if (paused) {
    return {
      compact: "AI Paused",
      long: "Kill Switch: Paused (AI execution blocked)",
      paused: true,
    };
  }
  return {
    compact: "AI Running",
    long: "Kill Switch: Running (AI execution allowed)",
    paused: false,
  };
}

function describeSandbox(
  sandbox: AiSandboxModeStatus | null,
  errored: boolean,
): { compact: string; long: string; on: boolean | null } {
  if (errored) {
    return { compact: "Sandbox ?", long: "Sandbox: unavailable", on: null };
  }
  if (sandbox === null) {
    return { compact: "Sandbox ?", long: "Sandbox: loading", on: null };
  }
  const enabled = Boolean(sandbox.sandboxEnabled ?? sandbox.isEnabled ?? false);
  if (enabled) {
    return { compact: "Sandbox ON", long: "Sandbox: ON (dry-run only)", on: true };
  }
  return { compact: "Sandbox OFF", long: "Sandbox: OFF", on: false };
}

function describeBriefing(
  briefing: DirectorBriefingSidebarStatus | null,
  errored: boolean,
): {
  compact: string;
  long: string;
  status: "ready" | "stale" | "critical" | "missing" | "unavailable";
} {
  if (errored) {
    return {
      compact: "Briefing ?",
      long: "Briefing: unavailable",
      status: "unavailable",
    };
  }
  if (briefing === null) {
    return { compact: "Briefing ?", long: "Briefing: loading", status: "unavailable" };
  }
  switch (briefing.status) {
    case "ready":
      return {
        compact: "Briefing READY",
        long: "Briefing: READY",
        status: "ready",
      };
    case "stale":
      return {
        compact: "Briefing STALE",
        long: "Briefing: STALE (older than 36h)",
        status: "stale",
      };
    case "critical":
      return {
        compact: "Briefing CRIT",
        long: "Briefing: CRITICAL (flags require attention)",
        status: "critical",
      };
    case "missing":
    default:
      return {
        compact: "Briefing —",
        long: "Briefing: none yet",
        status: "missing",
      };
  }
}

export function computeTopbarSafetySummary(
  inputs: TopbarSafetySummaryInputs,
): TopbarSafetySummary {
  const {
    killSwitch,
    sandbox,
    briefing,
    killSwitchError,
    sandboxError,
    briefingError,
  } = inputs;

  const anyLoading =
    (killSwitch === null && !killSwitchError) ||
    (sandbox === null && !sandboxError) ||
    (briefing === null && !briefingError);
  const allFetchesFailed = Boolean(
    killSwitchError && sandboxError && briefingError,
  );

  // 1. Loading - never claim a posture while any fetch is pending.
  if (anyLoading) {
    return {
      label: "Safety: Checking…",
      compactLabel: "Checking…",
      tone: "neutral",
      className: TONE_CLASS.neutral,
      tooltip: "Loading safety state…",
      dataStatus: "loading",
    };
  }

  // 2. Total fetch failure - everything is unavailable.
  if (allFetchesFailed) {
    return {
      label: "Safety: State unavailable",
      compactLabel: "State unavailable",
      tone: "neutral",
      className: TONE_CLASS.neutral,
      tooltip:
        "Safety state unavailable: kill switch, sandbox, and briefing fetches all failed.",
      dataStatus: "unavailable",
    };
  }

  const ks = describeKillSwitch(killSwitch, Boolean(killSwitchError));
  const sb = describeSandbox(sandbox, Boolean(sandboxError));
  const br = describeBriefing(briefing, Boolean(briefingError));

  const partialUnavailable =
    Boolean(killSwitchError) ||
    Boolean(sandboxError) ||
    Boolean(briefingError);

  // 3. Visual priority - amber if AI Paused, then danger if briefing
  // critical, then warning if any partial fetch failed or briefing
  // stale, then info if sandbox on, else success.
  let tone: TopbarSafetyTone;
  if (ks.paused === true) {
    tone = "warning";
  } else if (br.status === "critical") {
    tone = "danger";
  } else if (partialUnavailable || br.status === "stale") {
    tone = "warning";
  } else if (sb.on === true) {
    tone = "info";
  } else if (ks.paused === null) {
    // Kill-switch unavailable specifically - fall back to neutral
    // since we cannot claim safety. (Already covered by
    // partialUnavailable above, but kept explicit for clarity.)
    tone = "neutral";
  } else {
    tone = "success";
  }

  const label = `Safety: ${ks.compact} · ${sb.compact} · ${br.compact}`;
  // Compact label drops the "Safety:" prefix + shortens Sandbox to
  // SBOX and the Briefing prefix word so the pill fits between
  // ~768px and ~1280px without forcing the Topbar to overflow.
  const sbCompact = sb.compact.replace(/^Sandbox /, "SBOX ");
  const brCompact = br.compact.replace(/^Briefing /, "");
  const compactLabel = `${ks.compact} · ${sbCompact} · ${brCompact}`;
  const tooltip = `${ks.long}. ${sb.long}. ${br.long}. Read-only summary.`;

  let dataStatus: TopbarSafetySummary["dataStatus"];
  if (partialUnavailable && ks.paused === null) {
    dataStatus = "unavailable";
  } else if (ks.paused === true) {
    dataStatus = "ai_paused";
  } else if (ks.paused === false) {
    dataStatus = "ai_running";
  } else {
    dataStatus = "unavailable";
  }

  return {
    label,
    compactLabel,
    tone,
    className: TONE_CLASS[tone],
    tooltip,
    dataStatus,
  };
}

export const __testing__ = {
  describeKillSwitch,
  describeSandbox,
  describeBriefing,
  TONE_CLASS,
};
