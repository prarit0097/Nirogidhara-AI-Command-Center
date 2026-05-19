import "@testing-library/jest-dom";
import { beforeEach } from "vitest";

// Phase 13A — Tests that render `<App />` directly need a JWT in
// localStorage to get past the new <RequireAuth> wrapper. Seed a fake
// token before every test. Tests that explicitly need the unauthenticated
// state (login.test.tsx) clear localStorage in their own beforeEach.
beforeEach(() => {
  window.localStorage.setItem("nirogidhara.jwt", "test-jwt-token");
});

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => {},
  }),
});

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

window.ResizeObserver = ResizeObserverMock;
