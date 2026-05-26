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

/**
 * Phase 15K - inline auth-error predicate. We deliberately do NOT
 * import `isAuthError` from `@/services/api` because existing test
 * files mock `@/services/api` with a factory that only exports
 * `api` — importing a sibling export breaks those mocks. The
 * predicate mirrors `services/api.ts::isAuthError` exactly: it
 * matches the typed `AuthExpiredError` (via the `isAuthError`
 * marker field) and the duck-typed shape.
 */
function isAuthError(err: unknown): boolean {
  if (
    typeof err === "object" &&
    err !== null &&
    (err as { isAuthError?: unknown }).isAuthError === true
  ) {
    return true;
  }
  return false;
}
import { connectAuditEvents } from "@/services/realtime";
import type {
  ActivityEvent,
  AiSandboxModeStatus,
  DirectorBriefingSidebarStatus,
  RealtimeStatus,
  SaasRuntimeLiveGateKillSwitch,
} from "@/types/domain";
import { computeSafetyStatus, type SafetyStatusResult } from "@/utils/safetyStatus";
import {
  computeTopbarSafetySummary,
  type TopbarSafetySummary,
} from "@/utils/topbarSafetySummary";

/**
 * Phase 15G - audit-event kind prefixes that should trigger a
 * safety-state refresh. The provider subscribes to the existing
 * Phase 4A `/ws/audit/events/` WebSocket and only refreshes when an
 * allow-listed event lands. Anything else is ignored so the live
 * activity feed continues to flow at its own pace without driving
 * any extra GETs.
 *
 * Allow-list rationale:
 *   - `runtime.kill_switch.` (Phase 6H): backs the Phase 14D Topbar
 *     AI Paused / AI Kill Switch UI + Phase 15D Topbar Safety Pill.
 *   - `ai.sandbox.` (Phase 3D): backs the Phase 14E Sandbox Mode UI
 *     + Phase 15D Topbar Safety Pill.
 *   - `ceo_orchestration.snapshot.` (Phase 9F): backs the Phase 15B
 *     Sidebar Director Briefing badge + Phase 15D Topbar Safety
 *     Pill briefing token.
 */
export const SAFETY_REFRESH_EVENT_PREFIXES: readonly string[] = [
  "runtime.kill_switch.",
  "ai.sandbox.",
  "ceo_orchestration.snapshot.",
];

/**
 * Pure helper - returns true if `event.kind` is on the allow-list.
 * Exported so the provider test can assert the allow-list contract
 * without re-deriving the prefixes.
 */
export function shouldRefreshOnEvent(event: ActivityEvent | null | undefined): boolean {
  const kind = event?.kind;
  if (typeof kind !== "string" || kind.length === 0) return false;
  return SAFETY_REFRESH_EVENT_PREFIXES.some((prefix) =>
    kind.startsWith(prefix),
  );
}

/**
 * Phase 15G - debounce window for coalescing safety-refresh
 * requests. A burst of allow-listed events lands as a single
 * fetchAll() call rather than three back-to-back round-trips.
 */
export const SAFETY_REFRESH_DEBOUNCE_MS = 750;

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

/**
 * Phase 15H - lifecycle of the safety-sync audit-event WebSocket.
 *
 *   - "connecting"   - initial state before the socket has opened.
 *   - "live"         - socket is open; auto-refresh is reacting to
 *                      allow-listed events as they land.
 *   - "reconnecting" - socket closed; Phase 4A helper is attempting
 *                      exponential-backoff reconnect.
 *   - "offline"      - subscription was torn down (provider unmount
 *                      or caller-initiated close).
 *   - "unavailable"  - we never opened a socket (helper threw on
 *                      construction or `WebSocket` is missing from
 *                      the runtime).
 *
 * The first four states are forwarded verbatim from the existing
 * Phase 4A `RealtimeStatus` type; "unavailable" is a Phase 15H
 * extension for the construction-failure path so the Topbar
 * indicator can render a distinct neutral state instead of
 * misleading "reconnecting".
 */
export type SafetySyncStatus =
  | "connecting"
  | "live"
  | "reconnecting"
  | "offline"
  | "unavailable";

/**
 * Phase 15I - lightweight per-endpoint health for the Settings
 * diagnostics panel. Derived purely from the snapshot + error
 * flags already on `SafetyStateValue` so no new fetches are
 * issued. Three states:
 *
 *   - "loading" - the initial GET is still in flight (no snapshot,
 *     no error yet).
 *   - "ok"      - the latest GET returned successfully and the
 *     snapshot is on hand.
 *   - "error"   - the latest GET threw or returned a non-200.
 *
 * Mapping is intentionally narrow: the panel never surfaces raw
 * response bodies, status codes, or stack traces.
 */
export type SafetyEndpointStatus = "loading" | "ok" | "error";

/**
 * Phase 15L - source of the most recent refresh attempt. Exposed
 * so the Safety Diagnostics drawer can render the "Refresh source"
 * row from the actual provider state rather than the Phase 15J
 * timestamp-comparison heuristic. Buckets:
 *
 *   - "initial_load"  - the first fetch issued on provider mount.
 *   - "audit_event"   - a Phase 15G WebSocket event triggered a
 *                       debounced fetchAll().
 *   - "manual_refresh" - the operator clicked the Phase 15L
 *                       "Refresh status" button on the Safety
 *                       Diagnostics panel or detail drawer.
 *   - "unknown"       - no refresh has run yet (only really visible
 *                       during the very first render before
 *                       fetchAll resolves).
 */
export type SafetyRefreshSource =
  | "initial_load"
  | "audit_event"
  | "manual_refresh"
  | "unknown";

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
  // ---- Phase 15H sync health (read-only) --------------------------------
  /** Current lifecycle of the audit-event WebSocket. */
  safetySyncStatus: SafetySyncStatus;
  /** ISO timestamp of the most recent allow-listed safety event. */
  lastSafetyEventAt: string | null;
  /** ISO timestamp of the most recent debounced `refresh()` triggered by an event. */
  lastSafetyRefreshAt: string | null;
  // ---- Phase 15I per-endpoint health (read-only, derived) ---------------
  /** Health of the Phase 14D /runtime-live-gate/kill-switch/ GET. */
  killSwitchStatus: SafetyEndpointStatus;
  /** Health of the Phase 14E /ai/sandbox/status/ GET. */
  sandboxStatus: SafetyEndpointStatus;
  /** Health of the Phase 15B /ceo-orchestration/snapshots/sidebar-status/ GET. */
  briefingStatus: SafetyEndpointStatus;
  // ---- Phase 15L manual refresh (read-only) -----------------------------
  /** Source of the most recent refresh attempt. */
  lastRefreshSource: SafetyRefreshSource;
  /** True while a manual refresh round-trip is in flight. */
  refreshing: boolean;
  /**
   * Operator-triggered re-fetch of the same three safety GETs the
   * provider already owns. GET-only; never POST/PATCH/DELETE; never
   * mutates business or safety state. Idempotent — concurrent
   * clicks while a refresh is already in flight return the
   * in-flight promise rather than firing a second wave of fetches.
   */
  refreshSafetyState: () => Promise<void>;
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

/**
 * Phase 15I - pure helper. Maps {snapshot, error-flag} into one
 * of the three diagnostics buckets. Exported so the panel and the
 * tests share one source of truth.
 *
 *   - errored                              -> "error"
 *   - snapshot present (truthy)            -> "ok"
 *   - neither (still loading)              -> "loading"
 */
export function deriveEndpointStatus(
  hasSnapshot: boolean,
  errored: boolean,
): SafetyEndpointStatus {
  if (errored) return "error";
  if (hasSnapshot) return "ok";
  return "loading";
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

  // Phase 15H - WebSocket health surface. Initial state is
  // "connecting" because the Phase 4A helper opens the socket
  // synchronously on construction; the provider's effect flips
  // this to "live" / "reconnecting" / "offline" as the helper
  // fires `onStatusChange`. "unavailable" only ever fires when
  // the construction itself throws.
  const [safetySyncStatus, setSafetySyncStatus] = useState<SafetySyncStatus>(
    "connecting",
  );
  const [lastSafetyEventAt, setLastSafetyEventAt] = useState<string | null>(
    null,
  );
  const [lastSafetyRefreshAt, setLastSafetyRefreshAt] = useState<
    string | null
  >(null);

  // Phase 15L - manual refresh tracking.
  const [lastRefreshSource, setLastRefreshSource] = useState<SafetyRefreshSource>(
    "unknown",
  );
  const [refreshing, setRefreshing] = useState<boolean>(false);
  // In-flight promise — used so concurrent calls to
  // refreshSafetyState() return the same fetch instead of firing
  // a second parallel wave.
  const inFlightManualRefresh = useRef<Promise<void> | null>(null);

  // Guard against state updates after unmount (StrictMode dev render
  // pairs + Phase 13A 401 interceptor that auto-clears storage).
  const mounted = useRef(true);
  useEffect(
    () => () => {
      mounted.current = false;
    },
    [],
  );

  const fetchAll = useCallback(async (
    source: SafetyRefreshSource = "initial_load",
  ): Promise<void> => {
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
      // Phase 15K — suppress per-endpoint console.error spam on
      // auth-expired failures; the global Session expired toast
      // (deduped at the api layer) is the single source of truth.
      if (!isAuthError(ksRes.reason)) {
        // Logging matches the pre-15F Topbar behavior so existing
        // operator runbook expectations stay aligned.
        console.error(
          "[SafetyStateProvider] kill-switch load failed:",
          ksRes.reason,
        );
      }
      setKillSwitchError(true);
    }

    if (sbRes.status === "fulfilled") {
      setSandbox(sbRes.value);
      setSandboxError(false);
    } else {
      if (!isAuthError(sbRes.reason)) {
        console.error(
          "[SafetyStateProvider] sandbox load failed:",
          sbRes.reason,
        );
      }
      setSandboxError(true);
    }

    if (brRes.status === "fulfilled") {
      setBriefing(brRes.value);
      setBriefingError(null);
    } else {
      if (!isAuthError(brRes.reason)) {
        console.error(
          "[SafetyStateProvider] briefing load failed:",
          brRes.reason,
        );
      }
      setBriefingError(classifyBriefingError(brRes.reason));
    }

    // Phase 15L - record the source of this refresh attempt so
    // the diagnostics drawer can render "Refresh source" from
    // real state rather than the Phase 15J timestamp heuristic.
    setLastRefreshSource(source);
    setLoading(false);
  }, []);

  useEffect(() => {
    // Fire-and-forget; never await at the effect level.
    void fetchAll();
  }, [fetchAll]);

  // Phase 15G - subscribe once to the existing Phase 4A audit-event
  // WebSocket fan-out and re-run fetchAll() when an allow-listed
  // kill-switch / sandbox / briefing event lands. Refresh requests
  // are coalesced through a single debounced timer so a burst of
  // events lands as one round-trip instead of three back-to-back
  // refreshes.
  useEffect(() => {
    let debounceTimer: ReturnType<typeof setTimeout> | null = null;

    const triggerDebouncedRefresh = () => {
      if (!mounted.current) return;
      if (debounceTimer !== null) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        debounceTimer = null;
        if (!mounted.current) return;
        // Phase 15H - stamp the refresh timestamp BEFORE awaiting
        // so the indicator reflects the latest event-triggered
        // refresh attempt even if the network round-trip is slow.
        setLastSafetyRefreshAt(new Date().toISOString());
        // Phase 15L - tag the refresh source so the diagnostics
        // drawer's "Refresh source" row reports "Audit event".
        void fetchAll("audit_event");
      }, SAFETY_REFRESH_DEBOUNCE_MS);
    };

    let controller: { close: () => void } | null = null;
    try {
      controller = connectAuditEvents({
        onEvent: (event) => {
          if (shouldRefreshOnEvent(event)) {
            // Phase 15H - record the inbound timestamp regardless of
            // whether debounce coalesces this event into an existing
            // window. Operators can see "did anything land?" via the
            // Topbar indicator's hover title.
            if (mounted.current) {
              setLastSafetyEventAt(new Date().toISOString());
            }
            triggerDebouncedRefresh();
          }
        },
        // Phase 15H - mirror the Phase 4A lifecycle into local state
        // so the Topbar Safety Sync indicator can render the right
        // colour + label without re-implementing the helper's
        // reconnect machinery.
        onStatusChange: (status: RealtimeStatus) => {
          if (!mounted.current) return;
          setSafetySyncStatus(status);
        },
        // Initial snapshot is not used to drive refresh - the
        // initial Promise.allSettled fetch is the canonical
        // source for the first paint. Snapshot events are still
        // delivered to the WebSocket for other consumers; we just
        // ignore them here.
        onError: (err) => {
          // Stream errors are non-fatal: initial GETs still drive
          // the chrome. Log once so the operator can see why
          // auto-refresh isn't firing if they tail the console.
          console.warn("[SafetyStateProvider] audit-event stream error:", err);
        },
      });
    } catch (err) {
      // connectAuditEvents already swallows construction failures
      // and reconnects internally, but guard one more time so the
      // provider never crashes the chrome.
      console.warn(
        "[SafetyStateProvider] connectAuditEvents threw synchronously:",
        err,
      );
      // Phase 15H - construction-failure path. The socket never
      // opened, so reconnect isn't being attempted; flag the
      // indicator as "unavailable" so the operator sees a distinct
      // neutral state instead of misleading "connecting" forever.
      if (mounted.current) setSafetySyncStatus("unavailable");
    }

    return () => {
      if (debounceTimer !== null) {
        clearTimeout(debounceTimer);
        debounceTimer = null;
      }
      try {
        controller?.close();
      } catch {
        /* swallow - close should never throw */
      }
      // Phase 15H - the helper's onStatusChange also sets "offline"
      // when close() is called, but the effect-cleanup setter is a
      // belt-and-braces guarantee against React 18 StrictMode dev
      // double-mount leaking a stale "live" status.
      if (mounted.current) setSafetySyncStatus("offline");
    };
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

  // Phase 15I - per-endpoint diagnostics. Memoised so the panel
  // only re-renders when an individual endpoint actually flips.
  const killSwitchStatus = useMemo<SafetyEndpointStatus>(
    () => deriveEndpointStatus(killSwitch !== null, killSwitchError),
    [killSwitch, killSwitchError],
  );
  const sandboxStatus = useMemo<SafetyEndpointStatus>(
    () => deriveEndpointStatus(sandbox !== null, sandboxError),
    [sandbox, sandboxError],
  );
  const briefingStatus = useMemo<SafetyEndpointStatus>(
    () => deriveEndpointStatus(briefing !== null, briefingError !== null),
    [briefing, briefingError],
  );

  const setKillSwitch = useCallback(
    (next: SaasRuntimeLiveGateKillSwitch) => {
      if (!mounted.current) return;
      setKillSwitchState(next);
      setKillSwitchError(false);
    },
    [],
  );

  // Phase 15L - manual GET-only refresh triggered by the Safety
  // Diagnostics panel/drawer "Refresh status" button. Wraps the
  // existing fetchAll() with a `manual_refresh` source tag plus
  // a `refreshing` flag for button disable/loading state.
  // Idempotent under concurrent clicks: while a manual refresh
  // is in flight, additional calls return the same promise.
  const refreshSafetyState = useCallback(async (): Promise<void> => {
    if (!mounted.current) return;
    if (inFlightManualRefresh.current !== null) {
      return inFlightManualRefresh.current;
    }
    setRefreshing(true);
    setLastSafetyRefreshAt(new Date().toISOString());
    const promise = fetchAll("manual_refresh").finally(() => {
      if (mounted.current) setRefreshing(false);
      inFlightManualRefresh.current = null;
    });
    inFlightManualRefresh.current = promise;
    return promise;
  }, [fetchAll]);

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
      safetySyncStatus,
      lastSafetyEventAt,
      lastSafetyRefreshAt,
      killSwitchStatus,
      sandboxStatus,
      briefingStatus,
      lastRefreshSource,
      refreshing,
      refresh: fetchAll,
      refreshSafetyState,
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
      safetySyncStatus,
      lastSafetyEventAt,
      lastSafetyRefreshAt,
      killSwitchStatus,
      sandboxStatus,
      briefingStatus,
      lastRefreshSource,
      refreshing,
      fetchAll,
      refreshSafetyState,
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
    // Phase 15H inert defaults — used when the hook is consumed
    // outside the provider. "unavailable" is the safest default:
    // it tells the indicator there is no live socket without
    // misleading the operator into thinking we're connecting.
    safetySyncStatus: "unavailable",
    lastSafetyEventAt: null,
    lastSafetyRefreshAt: null,
    // Phase 15I - same "no provider" semantics: every endpoint
    // is treated as still loading so the panel never falsely
    // claims OK outside a real fetch lifecycle.
    killSwitchStatus: "loading",
    sandboxStatus: "loading",
    briefingStatus: "loading",
    // Phase 15L - inert defaults for the manual refresh fields.
    lastRefreshSource: "unknown",
    refreshing: false,
    refresh: async () => undefined,
    refreshSafetyState: async () => undefined,
    setKillSwitch: () => undefined,
  };
}

/** Exported for tests only. */
export const __testing__ = {
  SafetyStateContext,
  classifyBriefingError,
};
