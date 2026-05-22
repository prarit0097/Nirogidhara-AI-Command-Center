/**
 * Phase 14E-Hotfix-1 — pure helper for sidebar / chrome safety
 * status indicators.
 *
 * Priority (highest first):
 *   1. Kill switch active (AI paused) — overrides everything else.
 *   2. Sandbox mode ON — AI is running but in shadow-mode.
 *   3. Default — both safety surfaces report nominal state.
 *
 * Loading and error states are handled explicitly so the sidebar
 * never claims "All systems normal" while either backend fetch is
 * pending or has errored.
 *
 * The helper is intentionally pure — no api calls, no React deps.
 * Callers pass in the snapshots they already fetched.
 */
import type {
  AiSandboxModeStatus,
  SaasRuntimeLiveGateKillSwitch,
} from "@/types/domain";

export type SafetyStatusTone =
  | "warning"
  | "info"
  | "success"
  | "neutral";

export interface SafetyStatusResult {
  /** Human-readable label rendered next to the dot. */
  label: string;
  /** Semantic tone — sidebar maps this to a colour class. */
  tone: SafetyStatusTone;
  /**
   * Tailwind dot class. Pre-computed so the sidebar can render
   * without re-deriving from `tone`.
   */
  dotClass: string;
  /**
   * Whether the dot should pulse. Pulses are used for nominal /
   * loading states to convey "live"; the paused / sandbox states
   * are static so the operator's eye is drawn by colour, not
   * motion.
   */
  pulse: boolean;
}

/** Input shape — both fetches are optional so callers can call this
 * during loading / error states without crafting partial objects. */
export interface SafetyStatusInputs {
  killSwitch: SaasRuntimeLiveGateKillSwitch | null;
  sandbox: AiSandboxModeStatus | null;
  /** True while either backend fetch is still in flight. */
  loading?: boolean;
  /** True if the kill-switch fetch errored. */
  killSwitchError?: boolean;
  /** True if the sandbox fetch errored. */
  sandboxError?: boolean;
}

const RESULT_LOADING: SafetyStatusResult = {
  label: "Checking safety state…",
  tone: "neutral",
  dotClass: "bg-sidebar-foreground/40",
  pulse: true,
};

const RESULT_UNAVAILABLE: SafetyStatusResult = {
  // We deliberately do NOT show "All systems normal" when state
  // fetch fails — that would mislead the operator during the exact
  // moment they need accurate safety information.
  label: "Safety state unavailable",
  tone: "neutral",
  dotClass: "bg-sidebar-foreground/40",
  pulse: false,
};

const RESULT_PAUSED: SafetyStatusResult = {
  label: "AI paused by kill switch",
  tone: "warning",
  // Amber dot — matches the Topbar "AI Paused" indicator visual
  // language.
  dotClass: "bg-warning",
  pulse: false,
};

const RESULT_SANDBOX: SafetyStatusResult = {
  label: "Sandbox mode active",
  tone: "info",
  // Sky-blue dot — matches the Beaker icon hue on the Settings
  // Sandbox card.
  dotClass: "bg-info",
  pulse: false,
};

const RESULT_NORMAL: SafetyStatusResult = {
  label: "All systems normal",
  tone: "success",
  dotClass: "bg-success",
  pulse: true,
};

export function computeSafetyStatus(
  inputs: SafetyStatusInputs,
): SafetyStatusResult {
  const { killSwitch, sandbox, loading, killSwitchError, sandboxError } =
    inputs;

  // 1. While any fetch is in flight, never assert "normal".
  if (loading || (killSwitch === null && !killSwitchError) || (sandbox === null && !sandboxError)) {
    return RESULT_LOADING;
  }

  // 2. If either fetch errored, fail closed — do not assert normal.
  if (killSwitchError || sandboxError) {
    return RESULT_UNAVAILABLE;
  }

  // 3. Kill switch active wins outright — Phase 14D semantics.
  //    Phase 14D enriches the response with `aiExecutionBlocked` +
  //    `statusLabel: "paused"|"running"`. Use whichever is present;
  //    fall back to the canonical `enabled` field.
  const killPaused = Boolean(
    killSwitch?.aiExecutionBlocked ?? killSwitch?.enabled ?? false,
  );
  if (killPaused) {
    return RESULT_PAUSED;
  }

  // 4. Sandbox active is the second-highest signal.
  //    Phase 14E enriches the response with `sandboxEnabled` +
  //    `statusLabel: "enabled"|"disabled"`. Phase 3D `isEnabled`
  //    remains the canonical field — use that as the primary read.
  const sandboxOn = Boolean(
    sandbox?.sandboxEnabled ?? sandbox?.isEnabled ?? false,
  );
  if (sandboxOn) {
    return RESULT_SANDBOX;
  }

  // 5. Both green.
  return RESULT_NORMAL;
}

export const __testing__ = {
  RESULT_LOADING,
  RESULT_UNAVAILABLE,
  RESULT_PAUSED,
  RESULT_SANDBOX,
  RESULT_NORMAL,
};
