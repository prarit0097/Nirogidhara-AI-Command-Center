/**
 * Phase 15A — frontend tests for the read-only Rollback History
 * modal + the Settings card "View rollback history" button.
 *
 * Covers:
 *   - Settings card: "View rollback history" secondary button renders
 *     and is always enabled (history is useful even when no rollback
 *     candidates currently exist).
 *   - Click opens the RollbackHistoryModal.
 *   - Loading state renders.
 *   - Empty state renders.
 *   - Populated rows render with safe fields only (no prompt body
 *     leakage even when the mock includes poisoned text).
 *   - Agent filter narrows results.
 *   - HTTP 401 / 403 / generic errors render distinct messages.
 *   - Choose rollback target… is still available alongside the
 *     history button (Phase 14F regression).
 *   - Phase 14D + 14E + 14E-Hotfix-1 + 14F surfaces still co-render.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Settings from "@/pages/Settings";

// ---- api mock ----------------------------------------------------------

vi.mock("@/services/api", () => ({
  api: {
    getSettingsMock: vi.fn(),
    getWhatsAppProviderStatus: vi.fn(),
    getSaasRuntimeLiveGateKillSwitch: vi.fn(),
    postSaasRuntimeLiveGateKillSwitch: vi.fn(),
    getAiSandboxModeStatus: vi.fn(),
    postAiSandboxModeAction: vi.fn(),
    listPromptVersions: vi.fn(),
    postPromptVersionRollbackFromUi: vi.fn(),
    getPromptVersionRollbackHistory: vi.fn(),
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

import { api } from "@/services/api";

// ---- fixtures ----------------------------------------------------------

const killSwitchPaused = {
  scope: "global",
  enabled: true,
  runtimeKillSwitchEnabled: true,
  aiExecutionBlocked: true,
  statusLabel: "paused" as const,
  reason: "Production state",
  updatedAt: null,
  updatedBy: "",
  dryRun: true as const,
  liveExecutionAllowed: false as const,
  externalCallWillBeMade: false as const,
  killSwitchActive: true,
  approvalStatus: "",
  gateDecision: "blocked_by_kill_switch",
  blockers: ["global_runtime_kill_switch_enabled"],
  warnings: [],
  nextAction: "keep_live_execution_blocked",
  confirmationPhrases: {
    activateEmergencyStop: "ACTIVATE KILL SWITCH",
    resumeAiOperations: "RESUME AI OPERATIONS",
  },
};

const sandboxOff = {
  isEnabled: false,
  note: "",
  updatedBy: "",
  sandboxEnabled: false,
  statusLabel: "disabled" as const,
};

const promptVersions = [
  {
    id: "PV-80001",
    agent: "ceo",
    version: "v1.0",
    title: "CEO baseline",
    systemPolicy: "ceo v1 body",
    rolePrompt: "ceo v1 role",
    instructionPayload: {},
    isActive: false,
    status: "archived" as const,
    createdBy: "phase3d_admin",
    metadata: {},
    createdAt: "2026-04-01T10:00:00Z",
    activatedAt: null,
    rolledBackAt: null,
    rollbackReason: "",
  },
  {
    id: "PV-80002",
    agent: "ceo",
    version: "v2.0",
    title: "CEO live",
    systemPolicy: "ceo v2 body",
    rolePrompt: "ceo v2 role",
    instructionPayload: {},
    isActive: true,
    status: "active" as const,
    createdBy: "phase3d_admin",
    metadata: {},
    createdAt: "2026-05-01T10:00:00Z",
    activatedAt: "2026-05-01T10:01:00Z",
    rolledBackAt: null,
    rollbackReason: "",
  },
];

const SECRET_BODY_MARKER = "DO-NOT-RENDER-POISONED-PROMPT-BODY";

const historyResponse = {
  items: [
    {
      id: 1001,
      createdAt: "2026-05-22T07:00:00Z",
      kind: "prompt_version.rollback.ui_changed" as const,
      tone: "warning" as const,
      actor: "phase14f_admin",
      agent: "ceo",
      previousVersionId: "PV-80002",
      previousVersionLabel: "v2.0",
      targetVersionId: "PV-80001",
      targetVersionLabel: "v1.0",
      reason: "Phase 14F rollback after v2.0 regressed on safety phrases",
      matrixAction: "ai.prompt_version.activate",
      matrixStatus: "auto_approved",
      status: "rolled_back" as const,
      source: "settings_ui" as const,
      summary: "ceo rolled back from v2.0 to v1.0",
    },
    {
      id: 1002,
      createdAt: "2026-05-21T11:00:00Z",
      kind: "ai.prompt_version.rolled_back" as const,
      tone: "warning" as const,
      actor: "phase3d_admin",
      agent: "cfo",
      previousVersionId: "PV-80004",
      previousVersionLabel: "v2.0",
      targetVersionId: "PV-80003",
      targetVersionLabel: "v1.0",
      reason: "CFO numbers off — reverting to v1.0",
      matrixAction: "",
      matrixStatus: "",
      status: "rolled_back" as const,
      source: "service" as const,
      summary: "cfo rolled back from v2.0 to v1.0",
    },
  ],
  count: 2,
  limit: 50,
  offset: 0,
  kindsIncluded: [
    "prompt_version.rollback.ui_changed",
    "ai.prompt_version.rolled_back",
  ],
};

const seedBaseline = () => {
  (api.getSettingsMock as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
    approvalMatrix: [{ action: "Lead call", approval: "Auto" }],
    integrations: [],
    killSwitch: {},
  });
  (
    api.getWhatsAppProviderStatus as unknown as ReturnType<typeof vi.fn>
  ).mockResolvedValue(null);
  (
    api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
  ).mockResolvedValue(killSwitchPaused);
  (
    api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
  ).mockResolvedValue(sandboxOff);
  (
    api.listPromptVersions as unknown as ReturnType<typeof vi.fn>
  ).mockResolvedValue(promptVersions);
};

beforeEach(() => {
  vi.clearAllMocks();
  seedBaseline();
});

// ---- Settings card "View rollback history" button ---------------------

describe("Phase 15A — Settings card View rollback history button", () => {
  it("renders the View rollback history button alongside Choose rollback target", async () => {
    (
      api.getPromptVersionRollbackHistory as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(historyResponse);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    expect(
      await screen.findByTestId("settings-rollback-history-open"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("settings-rollback-open"),
    ).toBeInTheDocument();
  });

  it("opens the rollback history modal on click", async () => {
    (
      api.getPromptVersionRollbackHistory as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(historyResponse);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    fireEvent.click(
      await screen.findByTestId("settings-rollback-history-open"),
    );
    expect(
      await screen.findByTestId("rollback-history-modal-root"),
    ).toBeInTheDocument();
  });
});

// ---- RollbackHistoryModal states --------------------------------------

describe("Phase 15A — RollbackHistoryModal states", () => {
  it("shows loading state while history is being fetched", async () => {
    // Never-resolving promise to keep the modal in loading state.
    (
      api.getPromptVersionRollbackHistory as unknown as ReturnType<typeof vi.fn>
    ).mockReturnValue(new Promise(() => {}));

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    fireEvent.click(
      await screen.findByTestId("settings-rollback-history-open"),
    );

    expect(
      await screen.findByTestId("rollback-history-loading"),
    ).toBeInTheDocument();
  });

  it("shows empty state when no history exists", async () => {
    (
      api.getPromptVersionRollbackHistory as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue({
      items: [],
      count: 0,
      limit: 50,
      offset: 0,
      kindsIncluded: historyResponse.kindsIncluded,
    });

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    fireEvent.click(
      await screen.findByTestId("settings-rollback-history-open"),
    );

    expect(
      await screen.findByTestId("rollback-history-empty"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/No rollback history yet/i),
    ).toBeInTheDocument();
  });

  it("renders rows with safe metadata fields", async () => {
    (
      api.getPromptVersionRollbackHistory as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(historyResponse);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    fireEvent.click(
      await screen.findByTestId("settings-rollback-history-open"),
    );

    const modal = await screen.findByTestId("rollback-history-modal-root");

    // Both rows render.
    expect(
      within(modal).getByTestId("rollback-history-row-1001"),
    ).toBeInTheDocument();
    expect(
      within(modal).getByTestId("rollback-history-row-1002"),
    ).toBeInTheDocument();

    // Agent + version labels surface.
    const row1 = within(modal).getByTestId("rollback-history-row-1001");
    expect(row1.textContent).toContain("ceo");
    expect(row1.textContent).toContain("v2.0");
    expect(row1.textContent).toContain("v1.0");

    // Actor + reason surface.
    expect(row1.textContent).toContain("phase14f_admin");
    expect(row1.textContent).toContain(
      "Phase 14F rollback after v2.0 regressed",
    );

    // Source indicator differentiates UI vs Service rows.
    expect(row1.textContent?.toUpperCase()).toContain("UI");
    const row2 = within(modal).getByTestId("rollback-history-row-1002");
    expect(row2.textContent?.toUpperCase()).toContain("SERVICE");
  });

  it("does NOT leak prompt body content even when the mock contains it", async () => {
    // Poison the response with a body marker the modal must not render.
    (
      api.getPromptVersionRollbackHistory as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue({
      ...historyResponse,
      items: historyResponse.items.map((row) => ({
        ...row,
        // The modal must NOT read any of these legacy/sensitive keys.
        // We add them at runtime by widening the type so the test
        // can prove the modal ignores them.
        systemPolicy: SECRET_BODY_MARKER + " system",
        rolePrompt: SECRET_BODY_MARKER + " role",
        instructionPayload: { secret: SECRET_BODY_MARKER },
      })),
    });

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    fireEvent.click(
      await screen.findByTestId("settings-rollback-history-open"),
    );

    const modal = await screen.findByTestId("rollback-history-modal-root");
    expect(modal.textContent ?? "").not.toContain(SECRET_BODY_MARKER);
  });

  it("agent filter narrows the request", async () => {
    (
      api.getPromptVersionRollbackHistory as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(historyResponse);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    fireEvent.click(
      await screen.findByTestId("settings-rollback-history-open"),
    );
    const modal = await screen.findByTestId("rollback-history-modal-root");

    // First call on open — no agent filter.
    await waitFor(() => {
      const calls = (
        api.getPromptVersionRollbackHistory as unknown as ReturnType<typeof vi.fn>
      ).mock.calls;
      expect(calls.length).toBeGreaterThanOrEqual(1);
    });

    // Change the agent filter to cfo.
    fireEvent.change(
      within(modal).getByTestId("rollback-history-agent-filter"),
      { target: { value: "cfo" } },
    );

    await waitFor(() => {
      const calls = (
        api.getPromptVersionRollbackHistory as unknown as ReturnType<typeof vi.fn>
      ).mock.calls;
      const lastCall = calls[calls.length - 1];
      expect(lastCall[0]).toMatchObject({ agent: "cfo" });
    });
  });

  it("renders 401-specific error message", async () => {
    (
      api.getPromptVersionRollbackHistory as unknown as ReturnType<typeof vi.fn>
    ).mockRejectedValue(new Error("HTTP 401 — session expired"));

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    fireEvent.click(
      await screen.findByTestId("settings-rollback-history-open"),
    );

    const errorPanel = await screen.findByTestId("rollback-history-error");
    expect(errorPanel.getAttribute("data-error-status")).toBe("401");
    expect(errorPanel.textContent).toMatch(/Session expired/i);
  });

  it("renders 403-specific error message", async () => {
    (
      api.getPromptVersionRollbackHistory as unknown as ReturnType<typeof vi.fn>
    ).mockRejectedValue(new Error("HTTP 403 for /ai/prompt-versions/rollback-history/"));

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    fireEvent.click(
      await screen.findByTestId("settings-rollback-history-open"),
    );

    const errorPanel = await screen.findByTestId("rollback-history-error");
    expect(errorPanel.getAttribute("data-error-status")).toBe("403");
    expect(errorPanel.textContent).toMatch(/do not have permission/i);
  });

  it("renders generic unavailable message on other errors", async () => {
    (
      api.getPromptVersionRollbackHistory as unknown as ReturnType<typeof vi.fn>
    ).mockRejectedValue(new Error("Network down"));

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    fireEvent.click(
      await screen.findByTestId("settings-rollback-history-open"),
    );

    const errorPanel = await screen.findByTestId("rollback-history-error");
    expect(errorPanel.textContent).toMatch(/Rollback history unavailable/i);
  });
});

// ---- Phase 14D/14E/14F regression smoke -------------------------------

describe("Phase 15A — co-render with prior safety surfaces", () => {
  it("Rollback System + Sandbox + Kill Switch cards still co-render", async () => {
    (
      api.getPromptVersionRollbackHistory as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(historyResponse);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    // Phase 14D — paused state shows Resume button.
    expect(
      await screen.findByTestId("settings-kill-switch-resume"),
    ).toBeInTheDocument();
    // Phase 14E — sandbox OFF shows only the Enable button.
    expect(
      screen.getByTestId("settings-sandbox-enable"),
    ).toBeInTheDocument();
    // Phase 14F — Choose rollback target still present.
    expect(
      screen.getByTestId("settings-rollback-open"),
    ).toBeInTheDocument();
    // Phase 15A — new history button present.
    expect(
      screen.getByTestId("settings-rollback-history-open"),
    ).toBeInTheDocument();
  });
});
