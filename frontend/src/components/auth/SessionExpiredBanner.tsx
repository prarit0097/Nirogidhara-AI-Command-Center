/**
 * Phase 15K - Session Expired banner.
 *
 * Renders on the /login page when the user was just redirected
 * by RequireAuth because their JWT expired (or was missing). It
 * gives the operator a clean, accessible reason for the redirect
 * without showing any technical detail like the raw HTTP 401
 * message, response body, or stack trace.
 *
 * Hard guarantees:
 *   - Pure presentational. No fetches. No mutation.
 *   - Renders nothing when no `from` location state exists (i.e.
 *     when the user navigated to /login directly).
 *   - role="status" + aria-live="polite" so screen readers
 *     announce the message without interrupting input.
 *
 * The component reads `useLocation().state.from` so it only
 * appears when react-router put a `from` redirect state in
 * (the same state RequireAuth writes via `state={{ from: location }}`).
 */
import { useLocation } from "react-router-dom";
import { ShieldAlert } from "lucide-react";

interface LocationState {
  from?: { pathname?: string };
}

export function SessionExpiredBanner() {
  const location = useLocation();
  const state = location.state as LocationState | undefined;
  const from = state?.from?.pathname;
  // Only show the banner when react-router put a redirect-from
  // state on the location. A direct visit to /login renders no
  // banner so first-time logins stay clean.
  if (!from) return null;
  return (
    <div
      data-testid="session-expired-banner"
      role="status"
      aria-live="polite"
      className="rounded-lg border border-warning/40 bg-warning/10 px-4 py-3 text-[12.5px] text-warning"
    >
      <div className="flex items-start gap-3">
        <ShieldAlert
          className="h-4 w-4 shrink-0 mt-0.5"
          aria-hidden
        />
        <div className="space-y-1">
          <p className="font-semibold">Session expired</p>
          <p className="text-warning/80">
            Please sign in again to continue. Safety data may be stale
            until you sign in.
          </p>
        </div>
      </div>
    </div>
  );
}

export default SessionExpiredBanner;
