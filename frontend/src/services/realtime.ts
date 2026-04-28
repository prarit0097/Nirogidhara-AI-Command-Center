/**
 * Phase 4A — Realtime AuditEvent stream client.
 *
 * Wraps a single `/ws/audit/events/` WebSocket. Two responsibilities:
 *
 *  1. `buildWebSocketUrl(path)` — turns a relative WS path into an absolute
 *     `ws://` / `wss://` URL. Honours `VITE_WS_BASE_URL` when set;
 *     otherwise derives the origin from `VITE_API_BASE_URL` (swapping
 *     `http`→`ws` and `https`→`wss`).
 *
 *  2. `connectAuditEvents(opts)` — opens the socket, calls `onSnapshot`
 *     with the initial 25 rows, calls `onEvent` for every new
 *     AuditEvent, and reconnects with exponential backoff. Errors never
 *     escape (the dashboard / governance pages keep working from the
 *     existing polling endpoints when the socket is unavailable).
 *
 *  No business logic lives here — the service only carries server-shaped
 *  `ActivityEvent` rows verbatim.
 */
import type { ActivityEvent, RealtimeStatus } from "@/types/domain";

const RAW_API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";
const RAW_WS_BASE = import.meta.env.VITE_WS_BASE_URL ?? "";

function deriveWsOrigin(rawApiBase: string, rawWsBase: string): string {
  const explicit = (rawWsBase ?? "").trim();
  if (explicit) {
    return explicit.replace(/\/+$/, "");
  }
  const httpOrigin = (rawApiBase ?? "").trim().replace(/\/+$/, "");
  if (!httpOrigin) {
    return "ws://localhost:8000";
  }
  // Strip any "/api" suffix — the WS path lives at the host root.
  const withoutApi = httpOrigin.replace(/\/api$/i, "");
  if (withoutApi.startsWith("https://")) {
    return `wss://${withoutApi.slice("https://".length)}`;
  }
  if (withoutApi.startsWith("http://")) {
    return `ws://${withoutApi.slice("http://".length)}`;
  }
  if (withoutApi.startsWith("wss://") || withoutApi.startsWith("ws://")) {
    return withoutApi;
  }
  return `ws://${withoutApi}`;
}

export function buildWebSocketUrl(
  path: string = "/ws/audit/events/",
  options: { rawApiBase?: string; rawWsBase?: string; token?: string } = {},
): string {
  const origin = deriveWsOrigin(
    options.rawApiBase ?? RAW_API_BASE,
    options.rawWsBase ?? RAW_WS_BASE,
  );
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  const base = `${origin}${cleanPath}`;
  if (options.token) {
    const sep = base.includes("?") ? "&" : "?";
    return `${base}${sep}token=${encodeURIComponent(options.token)}`;
  }
  return base;
}

interface ConnectOptions {
  onSnapshot?: (events: ActivityEvent[]) => void;
  onEvent?: (event: ActivityEvent) => void;
  onStatusChange?: (status: RealtimeStatus) => void;
  onError?: (error: unknown) => void;
  // Optional — defaults to localStorage["nirogidhara.jwt"].
  token?: string | null;
  // Override path for tests / future endpoints.
  path?: string;
}

export interface RealtimeController {
  close: () => void;
  isLive: () => boolean;
  url: string;
}

const RECONNECT_DELAYS_MS = [1000, 2000, 4000, 8000, 15_000, 30_000];

export function connectAuditEvents(opts: ConnectOptions = {}): RealtimeController {
  const path = opts.path ?? "/ws/audit/events/";
  const token =
    opts.token ??
    (typeof window !== "undefined"
      ? window.localStorage.getItem("nirogidhara.jwt") ?? undefined
      : undefined);
  const url = buildWebSocketUrl(path, { token: token ?? undefined });

  let socket: WebSocket | null = null;
  let closedByCaller = false;
  let attempt = 0;

  const setStatus = (status: RealtimeStatus) => {
    try {
      opts.onStatusChange?.(status);
    } catch {
      /* swallow */
    }
  };

  const safeError = (err: unknown) => {
    try {
      opts.onError?.(err);
    } catch {
      /* swallow */
    }
  };

  const open = () => {
    if (closedByCaller) return;
    setStatus(attempt === 0 ? "connecting" : "reconnecting");

    let next: WebSocket;
    try {
      next = new WebSocket(url);
    } catch (err) {
      safeError(err);
      scheduleReconnect();
      return;
    }
    socket = next;

    next.onopen = () => {
      attempt = 0;
      setStatus("live");
    };

    next.onmessage = (msg) => {
      try {
        const parsed = JSON.parse(msg.data) as
          | { type: "audit.snapshot"; events: ActivityEvent[] }
          | { type: "audit.event"; event: ActivityEvent }
          | { type: "pong" }
          | { type: string };
        if (parsed.type === "audit.snapshot") {
          opts.onSnapshot?.(Array.isArray((parsed as { events: ActivityEvent[] }).events)
            ? (parsed as { events: ActivityEvent[] }).events
            : []);
        } else if (parsed.type === "audit.event") {
          const event = (parsed as { event?: ActivityEvent }).event;
          if (event) opts.onEvent?.(event);
        }
      } catch (err) {
        safeError(err);
      }
    };

    next.onerror = (err) => {
      safeError(err);
    };

    next.onclose = () => {
      socket = null;
      if (closedByCaller) {
        setStatus("offline");
        return;
      }
      scheduleReconnect();
    };
  };

  const scheduleReconnect = () => {
    if (closedByCaller) return;
    setStatus("reconnecting");
    const delay =
      RECONNECT_DELAYS_MS[Math.min(attempt, RECONNECT_DELAYS_MS.length - 1)];
    attempt += 1;
    setTimeout(open, delay);
  };

  open();

  return {
    close: () => {
      closedByCaller = true;
      try {
        socket?.close();
      } catch {
        /* swallow */
      }
      socket = null;
      setStatus("offline");
    },
    isLive: () => socket?.readyState === WebSocket.OPEN,
    url,
  };
}
