import { describe, expect, it } from "vitest";

import { buildWebSocketUrl } from "@/services/realtime";

describe("realtime — buildWebSocketUrl", () => {
  it("derives ws:// from an http API base", () => {
    const url = buildWebSocketUrl("/ws/audit/events/", {
      rawApiBase: "http://localhost:8000/api",
      rawWsBase: "",
    });
    expect(url).toBe("ws://localhost:8000/ws/audit/events/");
  });

  it("derives wss:// from an https API base and strips /api", () => {
    const url = buildWebSocketUrl("/ws/audit/events/", {
      rawApiBase: "https://commandcenter.nirogidhara.com/api",
      rawWsBase: "",
    });
    expect(url).toBe(
      "wss://commandcenter.nirogidhara.com/ws/audit/events/",
    );
  });

  it("honours an explicit VITE_WS_BASE_URL override", () => {
    const url = buildWebSocketUrl("/ws/audit/events/", {
      rawApiBase: "http://localhost:8000/api",
      rawWsBase: "wss://realtime.example.com",
    });
    expect(url).toBe("wss://realtime.example.com/ws/audit/events/");
  });

  it("falls back to localhost when no API base is provided", () => {
    const url = buildWebSocketUrl("/ws/audit/events/", {
      rawApiBase: "",
      rawWsBase: "",
    });
    expect(url.startsWith("ws://localhost:8000")).toBe(true);
  });

  it("appends ?token=… when a token is supplied", () => {
    const url = buildWebSocketUrl("/ws/audit/events/", {
      rawApiBase: "http://localhost:8000/api",
      rawWsBase: "",
      token: "jwt.example.token",
    });
    expect(url).toBe(
      "ws://localhost:8000/ws/audit/events/?token=jwt.example.token",
    );
  });
});
