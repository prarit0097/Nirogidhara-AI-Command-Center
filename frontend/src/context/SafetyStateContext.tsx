/**
 * Phase 15F - Shared Safety State Context.
 *
 * Centralises the three safety-related GETs that were previously
 * issued separately by both <Topbar /> and <Sidebar />:
 *   1. GET /api/v1/saas/runtime-live-gate/kill-switch/  (Phase 14D)
 *   2. GET /api/ai/sandbox/status/                      (Phase 14E)
 *   3. GET /api/v1/ceo-orchestration/snapshots/sidebar-status/
 *      (Phase 15B)
 *
 * After Phase 15F:
 *   - One fetch per endpoint per AppLayout mount.
 *   - Topbar and Sidebar consume the same snapshot, so their
 *     loading/error/state surfaces stay perfectly consistent.
 *   - A `refresh()` function lets a caller re-run all three GETs
 *     once (it does NOT poll).
 *
 * READ-ONLY. The provider never issues POST/PATCH/DELETE, never
 * mutates business state, never writes an AuditEvent, never
 * triggers a CEO briefing, never enqueues a Celery task.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api } from "@/services/api";
import type {
  AiSandboxModeStatus,
  DirectorBriefingSidebarStatus,
  SaasRuntimeLiveGateKillSwitch,
} from "@/types/domain";
import { computeSafetyStatus, type SafetyStatusResult } from "@/utils/safetyStatus";
import {
  computeTopbarSafetySummary,
  type TopbarSafetySummary,
} from "@/utils/topbarSafetySummary";

/**
 * Granular error tags surface which fetch(es) failed so the Topbar
 * pill (Phase 15D) can refuse to claim all-green and the Sidebar
 * indicator (Phase 14E-Hotfix-1) can fall back to "Safety state
 * unavailable".
 */
export type SafetyBriefingErrorKind =
  | "auth"
  | "permission"
  | "generic";

export interface SafetyStateValue {
  // ---- raw snapshots ----------------------------------------------------
  killSwitch: SaasRuntimeLiveGateKillSwitch | null;
  sandbox: AiSandboxModeStatus | null;
  briefing: DirectorBriefingSidebarStatus | null;
  // ---- error flags ------------------------------------------------------
  killSwitchError: boolean;
  sandboxError: boolean;
  briefingError: SafetyBriefingErrorKind | null;
  // ---- aggregate flags --------------------------------------------------
  loading: boolean;
  // ---- computed views (memoised; safe for direct render) ----------------
  sidebar: SafetyStatusResult;
  topbar: TopbarSafetySummary;
  // ---- callbacks --------------------------------------------------------
  /** Re-fetches all three endpoints once. Returns when all settle. */
  refresh: () => Promise<void>;
  /**
   * Setter the Topbar uses after the KillSwitchModal posts a new
   * state - lets the kill-switch GET be skipped on the immediate
   * follow-up render without forcing a refetch round-trip.
   */
  setKillSwitch: (next: SaasRuntimeLiveGateKillSwitch) => void;
}

const SafetyStateContext = createContext<SafetyStateValue | null>(null);

/**
 * Map an arbitrary thrown Error/value into one of the three
 * Phase 15B briefing-specific error tags so the CEO nav badge
 * shows "Session expired" / "Unavailable" / "Error" correctly.
 * Anything that isn't a recognised auth / permission HTTP code
 * falls through to "generic".
 */
function classifyBriefingError(err: unknown): SafetyBriefingErrorKind {
  const message = err instanceof Error ? err.message : "";
  if (message.includes("401")) return "auth";
  if (message.includes("403")) return "permission";
  return "generic";
}

export function SafetyStateProvider({ children }: { children: ReactNode }) {
  const [killSwitch, setKillSwitchState] = useState<
    SaasRuntimeLiveGateKillSwitch | null
  >(null);
  const [sandbox, setSandbox] = useState<AiSandboxModeStatus | null>(null);
  const [briefing, setBriefing] = useState<
    DirectorBriefingSidebarStatus | null
  >(null);

  const [killSwitchError, setKillSwitchError] = useState(false);
  const [sandboxError, setSandboxError] = useState(false);
  const [briefingError, setBriefingError] =
    useState<SafetyBriefingErrorKind | null>(null);

  const [loading, setLoading] = useState(true);

  // Guard against state updates after unmount (StrictMode dev render
  // pairs + Phase 13A 401 interceptor that auto-clears storage).
  const mounted = useRef(true);
  useEffect(
    () => () => {
      mounted.current = false;
    },
    [],
  );

  const fetchAll = useCallback(async (): Promise<void> => {
    if (mounted.current) setLoading(true);
    const results = await Promise.allSettled([
      api.getSaasRuntimeLiveGateKillSwitch(),
      api.getAiSandboxModeStatus(),
      api.getDirectorBriefingSidebarStatus(),
    ]);
    if (!mounted.current) return;

    const [ksRes, sbRes, brRes] = results;

    if (ksRes.status === "fulfilled") {
      setKillSwitchState(ksRes.value);
      setKillSwitchError(false);
    } else {
      // Logging matches the pre-15F Topbar behavior so existing
      // operator runbook expectations stay aligned.
      console.error(
        "[SafetyStateProvider] kill-switch load failed:",
        ksRes.reason,
      );
      setKillSwitchError(true);
    }

    if (sbRes.status === "fulfilled") {
      setSandbox(sbRes.value);
      setSandboxError(false);
    } else {
      console.error(
        "[SafetyStateProvider] sandbox load failed:",
        sbRes.reason,
      );
      setSandboxError(true);
    }

    if (brRes.status === "fulfilled") {
      setBriefing(brRes.value);
      setBriefingError(null);
    } else {
      console.error(
        "[SafetyStateProvider] briefing load failed:",
        brRes.reason,
      );
      setBriefingError(classifyBriefingError(brRes.reason));
    }

    setLoading(false);
  }, []);

  useEffect(() => {
    // Fire-and-forget; never await at the effect level.
    void fetchAll();
  }, [fetchAll]);

  const sidebar = useMemo<SafetyStatusResult>(
    () =>
      computeSafetyStatus({
        killSwitch,
        sandbox,
        killSwitchError,
        sandboxError,
      }),
    [killSwitch, sandbox, killSwitchError, sandboxError],
  );

  const topbar = useMemo<TopbarSafetySummary>(
    () =>
      computeTopbarSafetySummary({
        killSwitch,
        sandbox,
        briefing,
        killSwitchError,
        sandboxError,
        // The Topbar helper takes a boolean briefingError flag,
        // not the granular tag - any non-null tag means errored.
        briefingError: briefingError !== null,
      }),
    [killSwitch, sandbox, briefing, killSwitchError, sandboxError, briefingError],
  );

  const setKillSwitch = useCallback(
    (next: SaasRuntimeLiveGateKillSwitch) => {
      if (!mounted.current) return;
      setKillSwitchState(next);
      setKillSwitchError(false);
    },
    [],
  );

  const value = useMemo<SafetyStateValue>(
    () => ({
      killSwitch,
      sandbox,
      briefing,
      killSwitchError,
      sandboxError,
      briefingError,
      loading,
      sidebar,
      topbar,
      refresh: fetchAll,
      setKillSwitch,
    }),
    [
      killSwitch,
      sandbox,
      briefing,
      killSwitchError,
      sandboxError,
      briefingError,
      loading,
      sidebar,
      topbar,
      fetchAll,
      setKillSwitch,
    ],
  );

  return (
    <SafetyStateContext.Provider value={value}>
      {children}
    </SafetyStateContext.Provider>
  );
}

/**
 * Consumer hook. Returns the live shared safety snapshot. If the
 * component is rendered outside a SafetyStateProvider (e.g. in
 * isolation tests), the hook falls back to an inert "loading"
 * snapshot so unrelated tests don't have to set up the provider.
 */
export function useSafetyState(): SafetyStateValue {
  const ctx = useContext(SafetyStateContext);
  if (ctx !== null) return ctx;
  // Inert fallback - mirrors the loading state. Avoids throwing
  // so the chrome components don't crash if rendered outside the
  // provider (e.g. when an unrelated component test renders the
  // Sidebar without a provider). Both helper outputs match what
  // computeSafetyStatus / computeTopbarSafetySummary would produce
  // for the "all-null, no errors" loading case.
  return {
    killSwitch: null,
    sandbox: null,
    briefing: null,
    killSwitchError: false,
    sandboxError: false,
    briefingError: null,
    loading: true,
    sidebar: computeSafetyStatus({ killSwitch: null, sandbox: null }),
    topbar: computeTopbarSafetySummary({
      killSwitch: null,
      sandbox: null,
      briefing: null,
    }),
    refresh: async () => undefined,
    setKillSwitch: () => undefined,
  };
}

/** Exported for tests only. */
export const __testing__ = {
  SafetyStateContext,
  classifyBriefingError,
};
