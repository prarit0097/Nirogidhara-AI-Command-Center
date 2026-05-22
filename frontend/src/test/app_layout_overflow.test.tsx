/**
 * Phase 15E - structural test for the AppLayout overflow guard.
 *
 * JSDOM cannot reliably measure real horizontal scroll layout, so we
 * assert the structural class that prevents the body-level scrollbar
 * (overflow-x-clip on the right-content container + min-w-0 on
 * <main>). These classes were added in Phase 15E to fix the
 * regression observed after Phase 15D's Topbar Safety Pill.
 *
 * The test stays read-only end-to-end - no business state touched,
 * no provider call, no AuditEvent written.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AppLayout } from "@/components/layout/AppLayout";

// ---- api mock ----------------------------------------------------------

vi.mock("@/services/api", () => ({
  api: {
    getSaasRuntimeLiveGateKillSwitch: vi.fn().mockResolvedValue({
      scope: "global",
      enabled: false,
      runtimeKillSwitchEnabled: false,
      aiExecutionBlocked: false,
      statusLabel: "running",
      reason: "",
      updatedAt: null,
      updatedBy: "",
      dryRun: true,
      liveExecutionAllowed: false,
      externalCallWillBeMade: false,
      killSwitchActive: false,
      approvalStatus: "",
      gateDecision: "kill_switch_disabled",
      blockers: [],
      warnings: [],
      nextAction: "keep_live_execution_blocked",
    }),
    getAiSandboxModeStatus: vi.fn().mockResolvedValue({
      isEnabled: false,
      note: "",
      updatedBy: "",
      sandboxEnabled: false,
      statusLabel: "disabled",
    }),
    getDirectorBriefingSidebarStatus: vi.fn().mockResolvedValue({
      status: "missing",
      label: "No briefing yet",
      latestSnapshotId: null,
      latestSnapshotAt: null,
      ageMinutes: null,
      healthScore: null,
      tier: null,
      targetRoute: "/ceo-ai",
    }),
    getSaasCurrentOrganization: vi.fn().mockResolvedValue({
      organization: { id: 1, code: "nirogidhara", name: "Nirogidhara" },
      branch: null,
      userOrgRole: "owner",
      memberships: [],
      settings: [],
      featureFlags: [],
    }),
  },
}));

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route
            path="/"
            element={
              <div data-testid="dummy-page">Phase 15E page body</div>
            }
          />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("Phase 15E - AppLayout horizontal overflow guard", () => {
  it("renders the right-content wrapper with overflow-x-clip", () => {
    renderLayout();
    const wrapper = screen.getByTestId("app-layout-content");
    expect(wrapper.className).toContain("overflow-x-clip");
  });

  it("preserves the left sidebar padding offset classes", () => {
    renderLayout();
    const wrapper = screen.getByTestId("app-layout-content");
    // Default state (collapsed=false) -> lg:pl-[260px]; when
    // collapsed -> lg:pl-[72px]. We only check the default render.
    expect(wrapper.className).toContain("lg:pl-[260px]");
  });

  it("<main> carries min-w-0 so wide child content cannot push the layout out", () => {
    renderLayout();
    // The <main> ancestor of the dummy page should now carry
    // min-w-0 alongside the existing max-w-[1600px].
    const page = screen.getByTestId("dummy-page");
    const main = page.closest("main");
    expect(main).not.toBeNull();
    expect(main?.className).toContain("min-w-0");
    expect(main?.className).toContain("max-w-[1600px]");
  });

  it("does not regress: page body still renders inside the layout", () => {
    renderLayout();
    expect(screen.getByTestId("dummy-page")).toBeInTheDocument();
  });
});
