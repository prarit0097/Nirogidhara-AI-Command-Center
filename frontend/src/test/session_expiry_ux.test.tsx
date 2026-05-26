/**
 * Phase 15K - tests for the Session Expiry UX polish.
 *
 * Covers:
 *   - AuthExpiredError class + isAuthError predicate.
 *   - safeFetch wraps a real 401 as an AuthExpiredError + dispatches
 *     `nirogidhara:auth-cleared` + clears the JWT from localStorage.
 *   - The global "Session expired" sonner toast fires exactly ONCE
 *     across multiple 401 responses (dedupe contract).
 *   - The raw "HTTP 401 - session expired or unauthenticated" string
 *     never reaches a per-widget toast surface.
 *   - SessionExpiredBanner renders only when a `from` redirect
 *     state exists on the location (i.e. RequireAuth sent the user
 *     to /login).
 *   - Banner renders nothing when the user visited /login directly.
 *   - Banner is accessible: role="status", aria-live="polite",
 *     literal "Session expired" + sign-in-again copy.
 *   - safeFetch never returns mock data for a 401 even in dev mode.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import {
  AuthExpiredError,
  isAuthError,
  __resetSessionExpiredToastForTest,
  api,
} from "@/services/api";
import { SessionExpiredBanner } from "@/components/auth/SessionExpiredBanner";

// ---- helpers -----------------------------------------------------------

const toastErrorMock = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    error: (...args: unknown[]) => toastErrorMock(...args),
    success: vi.fn(),
    info: vi.fn(),
    message: vi.fn(),
    warning: vi.fn(),
  },
}));

const originalFetch = global.fetch;

beforeEach(() => {
  __resetSessionExpiredToastForTest();
  toastErrorMock.mockReset();
  // Default-clear the stored JWT before each test so the auth
  // interceptor's removal is observable.
  window.localStorage.setItem("nirogidhara.jwt", "test-jwt");
});

afterEach(() => {
  global.fetch = originalFetch;
  window.localStorage.removeItem("nirogidhara.jwt");
});

function mockFetch(status: number, body: unknown = {}): void {
  global.fetch = vi.fn(async () =>
    Promise.resolve({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    } as unknown as Response),
  ) as unknown as typeof fetch;
}

// ---- AuthExpiredError + isAuthError ----------------------------------

describe("Phase 15K - AuthExpiredError + isAuthError", () => {
  it("AuthExpiredError carries the auth-error flag and HTTP 401 status", () => {
    const err = new AuthExpiredError();
    expect(err.name).toBe("AuthExpiredError");
    expect(err.isAuthError).toBe(true);
    expect(err.httpStatus).toBe(401);
    expect(err.message).toBe("Session expired or unauthenticated");
  });

  it("isAuthError recognises AuthExpiredError instances + duck-typed shape", () => {
    expect(isAuthError(new AuthExpiredError())).toBe(true);
    expect(isAuthError({ isAuthError: true })).toBe(true);
    expect(isAuthError(new Error("HTTP 500 for /api/x"))).toBe(false);
    expect(isAuthError("not an error")).toBe(false);
    expect(isAuthError(null)).toBe(false);
    expect(isAuthError(undefined)).toBe(false);
  });
});

// ---- safeFetch 401 contract -----------------------------------------

describe("Phase 15K - safeFetch wraps 401 as AuthExpiredError", () => {
  it("throws AuthExpiredError + clears JWT + dispatches auth-cleared + fires ONE global toast", async () => {
    mockFetch(401);
    const authClearedSpy = vi.fn();
    window.addEventListener("nirogidhara:auth-cleared", authClearedSpy);

    let caught: unknown;
    try {
      // Any safeFetch-backed method works; pick the kill-switch GET.
      await api.getSaasRuntimeLiveGateKillSwitch();
    } catch (err) {
      caught = err;
    }
    // Wait one tick so the dynamic sonner import + toast call settle.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(isAuthError(caught)).toBe(true);
    expect(window.localStorage.getItem("nirogidhara.jwt")).toBeNull();
    expect(authClearedSpy).toHaveBeenCalled();
    expect(toastErrorMock).toHaveBeenCalledTimes(1);
    expect(toastErrorMock.mock.calls[0]?.[0]).toBe("Session expired");
    const opts = toastErrorMock.mock.calls[0]?.[1] as
      | { description?: string }
      | undefined;
    expect(opts?.description).toContain("Please sign in again");

    window.removeEventListener("nirogidhara:auth-cleared", authClearedSpy);
  });

  it("multiple 401 responses across consecutive calls fire the global toast only ONCE", async () => {
    mockFetch(401);

    for (let i = 0; i < 5; i += 1) {
      try {
        await api.getSaasRuntimeLiveGateKillSwitch();
      } catch {
        /* expected AuthExpiredError */
      }
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });
    }
    expect(toastErrorMock).toHaveBeenCalledTimes(1);
  });

  it("the raw 'HTTP 401 - session expired or unauthenticated' text never reaches the toast", async () => {
    mockFetch(401);
    try {
      await api.getSaasRuntimeLiveGateKillSwitch();
    } catch {
      /* expected */
    }
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(toastErrorMock).toHaveBeenCalledTimes(1);
    const [title, opts] = toastErrorMock.mock.calls[0] ?? [];
    const description = (opts as { description?: string } | undefined)
      ?.description;
    // Title must NOT contain the raw HTTP string.
    expect(String(title)).not.toContain("HTTP 401");
    expect(String(title)).not.toContain("unauthenticated");
    // Description must NOT contain it either.
    expect(String(description)).not.toContain("HTTP 401");
    expect(String(description)).not.toContain("unauthenticated");
  });

  it("safeFetch does NOT fall back to mock data on 401 (even in dev)", async () => {
    mockFetch(401);
    let caught: unknown;
    try {
      // Dashboard activity has a generous mock fallback; verify the
      // 401 still throws AuthExpiredError instead of returning mocks.
      await api.getLiveActivityFeed();
    } catch (err) {
      caught = err;
    }
    expect(isAuthError(caught)).toBe(true);
  });
});

// ---- SessionExpiredBanner --------------------------------------------

describe("Phase 15K - SessionExpiredBanner", () => {
  it("renders the banner when the location has a `from` redirect state", () => {
    render(
      <MemoryRouter
        initialEntries={[
          { pathname: "/login", state: { from: { pathname: "/settings" } } },
        ]}
      >
        <Routes>
          <Route path="/login" element={<SessionExpiredBanner />} />
        </Routes>
      </MemoryRouter>,
    );
    const banner = screen.getByTestId("session-expired-banner");
    expect(banner).toBeInTheDocument();
    expect(banner.getAttribute("role")).toBe("status");
    expect(banner.getAttribute("aria-live")).toBe("polite");
    expect(banner.textContent || "").toContain("Session expired");
    expect(banner.textContent || "").toContain("Please sign in again");
  });

  it("renders NOTHING when the user visits /login directly (no redirect state)", () => {
    render(
      <MemoryRouter initialEntries={[{ pathname: "/login" }]}>
        <Routes>
          <Route path="/login" element={<SessionExpiredBanner />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.queryByTestId("session-expired-banner")).toBeNull();
  });

  it("never renders technical/raw HTTP strings", () => {
    render(
      <MemoryRouter
        initialEntries={[
          { pathname: "/login", state: { from: { pathname: "/settings" } } },
        ]}
      >
        <Routes>
          <Route path="/login" element={<SessionExpiredBanner />} />
        </Routes>
      </MemoryRouter>,
    );
    const text =
      screen.getByTestId("session-expired-banner").textContent || "";
    for (const forbidden of [
      "HTTP 401",
      "unauthenticated",
      "Bearer ",
      "Authorization",
      "Traceback",
      "stack",
    ]) {
      expect(text).not.toContain(forbidden);
    }
  });
});
