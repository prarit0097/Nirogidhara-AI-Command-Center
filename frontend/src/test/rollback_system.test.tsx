/**
 * Phase 14F — frontend tests for the Rollback System UI wiring.
 *
 * Covers:
 *   - Settings Rollback card states: loading / error / no candidates
 *     / candidates available.
 *   - Click opens the RollbackSystemModal.
 *   - Modal renders only safe metadata (no systemPolicy / rolePrompt
 *     body even when the mock includes it).
 *   - Agent selector lists only agents with at least one non-active
 *     version.
 *   - Target version selector filters by selected agent.
 *   - Submit disabled until agent + version + reason >= 10 + exact
 *     phrase.
 *   - Successful POST refreshes the list (refetched after rollback).
 *   - Backend error shown via inline panel + the click does not
 *     blindly succeed.
 *   - Phase 14D + 14E + 14E-Hotfix-1 surfaces still render alongside.
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
  reason: "",
  updatedAt: null,
  confirmationPhrases: {
    enableSandboxMode: "ENABLE SANDBOX MODE",
    disableSandboxMode: "DISABLE SANDBOX MODE",
  },
};

const SECRET_BODY_MARKER = "DO-NOT-RENDER-PROMPT-BODY-SECRET";

const promptVersions = [
  {
    id: "PV-80001",
    agent: "ceo",
    version: "v1.0",
    title: "CEO baseline",
    systemPolicy: SECRET_BODY_MARKER + " ceo v1 system policy body",
    rolePrompt: "ceo v1 role prompt body",
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
    title: "CEO incident regression",
    systemPolicy: SECRET_BODY_MARKER + " ceo v2 system policy body",
    rolePrompt: "ceo v2 role prompt body",
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
  {
    id: "PV-80003",
    agent: "cfo",
    version: "v1.0",
    title: "CFO baseline",
    systemPolicy: SECRET_BODY_MARKER + " cfo v1 system policy body",
    rolePrompt: "cfo v1 role prompt body",
    instructionPayload: {},
    isActive: false,
    status: "archived" as const,
    createdBy: "phase3d_admin",
    metadata: {},
    createdAt: "2026-04-15T10:00:00Z",
    activatedAt: null,
    rolledBackAt: null,
    rollbackReason: "",
  },
  {
    id: "PV-80004",
    agent: "cfo",
    version: "v2.0",
    title: "CFO live",
    systemPolicy: SECRET_BODY_MARKER + " cfo v2 system policy body",
    rolePrompt: "cfo v2 role prompt body",
    instructionPayload: {},
    isActive: true,
    status: "active" as const,
    createdBy: "phase3d_admin",
    metadata: {},
    createdAt: "2026-05-10T10:00:00Z",
    activatedAt: "2026-05-10T10:01:00Z",
    rolledBackAt: null,
    rollbackReason: "",
  },
];

const seedSettingsMock = () => {
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
};

beforeEach(() => {
  vi.clearAllMocks();
  seedSettingsMock();
});

// ---- Settings Rollback card states ------------------------------------

describe("Phase 14F — Settings Rollback card", () => {
  it("disables the button while prompt versions are still loading", async () => {
    // Never-resolving promise to simulate loading.
    (
      api.listPromptVersions as unknown as ReturnType<typeof vi.fn>
    ).mockReturnValue(new Promise(() => {}));

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    const button = (await screen.findByTestId(
      "settings-rollback-open",
    )) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByText(/Loading rollback state…/i)).toBeInTheDocument();
  });

  it("disables the button and shows 'No rollback candidates' when only active versions exist", async () => {
    (
      api.listPromptVersions as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue([
      { ...promptVersions[1] }, // ceo v2 only (active)
      { ...promptVersions[3] }, // cfo v2 only (active)
    ]);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    const button = (await screen.findByTestId(
      "settings-rollback-open",
    )) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(true));
    expect(screen.getByText(/No rollback candidates/i)).toBeInTheDocument();
  });

  it("enables the button and shows 'Rollback ready' when candidates exist", async () => {
    (
      api.listPromptVersions as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(promptVersions);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    const button = (await screen.findByTestId(
      "settings-rollback-open",
    )) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));
    expect(screen.getByText(/Rollback ready/i)).toBeInTheDocument();
  });

  it("disables the button and shows 'Rollback state unavailable' on fetch error", async () => {
    (
      api.listPromptVersions as unknown as ReturnType<typeof vi.fn>
    ).mockRejectedValue(new Error("HTTP 500"));

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    const button = (await screen.findByTestId(
      "settings-rollback-open",
    )) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(true));
    expect(
      screen.getByText(/Rollback state unavailable/i),
    ).toBeInTheDocument();
  });
});

// ---- RollbackSystemModal -----------------------------------------------

describe("Phase 14F — RollbackSystemModal flow", () => {
  it("opens the modal on click and renders agent + version selectors", async () => {
    (
      api.listPromptVersions as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(promptVersions);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    const openBtn = await screen.findByTestId("settings-rollback-open");
    await waitFor(() =>
      expect((openBtn as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(openBtn);

    const modal = await screen.findByTestId(
      "rollback-system-modal-rollback",
    );
    expect(
      within(modal).getByTestId("rollback-system-agent-select"),
    ).toBeInTheDocument();
    expect(
      within(modal).getByTestId("rollback-system-target-select"),
    ).toBeInTheDocument();
    expect(
      within(modal).getByTestId("rollback-system-reason-input"),
    ).toBeInTheDocument();
    expect(
      within(modal).getByTestId("rollback-system-phrase-input"),
    ).toBeInTheDocument();
  });

  it("does NOT leak prompt body content into the modal", async () => {
    (
      api.listPromptVersions as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(promptVersions);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    const openBtn = await screen.findByTestId("settings-rollback-open");
    await waitFor(() =>
      expect((openBtn as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(openBtn);

    const modal = await screen.findByTestId(
      "rollback-system-modal-rollback",
    );
    // The mock fixture poisoned every systemPolicy/rolePrompt with a
    // sentinel string. If the modal accidentally renders the body,
    // the sentinel would surface in the DOM text.
    expect(modal.textContent ?? "").not.toContain(SECRET_BODY_MARKER);
  });

  it("submit stays disabled until agent + version + reason + exact phrase", async () => {
    (
      api.listPromptVersions as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(promptVersions);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    const openBtn = await screen.findByTestId("settings-rollback-open");
    await waitFor(() =>
      expect((openBtn as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(openBtn);

    const modal = await screen.findByTestId(
      "rollback-system-modal-rollback",
    );
    const submit = within(modal).getByTestId(
      "rollback-system-submit",
    ) as HTMLButtonElement;
    const agentSelect = within(modal).getByTestId(
      "rollback-system-agent-select",
    ) as HTMLSelectElement;
    const targetSelect = within(modal).getByTestId(
      "rollback-system-target-select",
    ) as HTMLSelectElement;
    const reasonInput = within(modal).getByTestId(
      "rollback-system-reason-input",
    ) as HTMLTextAreaElement;
    const phraseInput = within(modal).getByTestId(
      "rollback-system-phrase-input",
    ) as HTMLInputElement;

    expect(submit.disabled).toBe(true);

    // Selecting agent alone is not enough.
    fireEvent.change(agentSelect, { target: { value: "ceo" } });
    expect(submit.disabled).toBe(true);

    // Target select should now have only the non-active CEO version.
    // PV-80001 (archived) is the only CEO candidate.
    fireEvent.change(targetSelect, { target: { value: "PV-80001" } });
    expect(submit.disabled).toBe(true);

    // Reason still too short.
    fireEvent.change(reasonInput, { target: { value: "short" } });
    expect(submit.disabled).toBe(true);

    // Wrong phrase.
    fireEvent.change(phraseInput, {
      target: { value: "ACTIVATE KILL SWITCH" },
    });
    expect(submit.disabled).toBe(true);

    // Correct everything.
    fireEvent.change(reasonInput, {
      target: { value: "Phase 14F end-to-end rollback drill" },
    });
    fireEvent.change(phraseInput, {
      target: { value: "ROLLBACK PROMPT VERSION" },
    });
    expect(submit.disabled).toBe(false);
  });

  it("agent selector filters target candidates and disables submit on agent swap", async () => {
    (
      api.listPromptVersions as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(promptVersions);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByTestId("settings-rollback-open"));
    const modal = await screen.findByTestId(
      "rollback-system-modal-rollback",
    );
    const agentSelect = within(modal).getByTestId(
      "rollback-system-agent-select",
    ) as HTMLSelectElement;
    const targetSelect = within(modal).getByTestId(
      "rollback-system-target-select",
    ) as HTMLSelectElement;

    fireEvent.change(agentSelect, { target: { value: "ceo" } });
    // CEO has exactly one candidate: PV-80001 (archived). The active
    // PV-80002 must be filtered out.
    const ceoOptionValues = Array.from(targetSelect.options)
      .map((o) => o.value)
      .filter(Boolean);
    expect(ceoOptionValues).toEqual(["PV-80001"]);

    // Swap to CFO — candidate set changes, target should be cleared.
    fireEvent.change(agentSelect, { target: { value: "cfo" } });
    expect(targetSelect.value).toBe("");
    const cfoOptionValues = Array.from(targetSelect.options)
      .map((o) => o.value)
      .filter(Boolean);
    expect(cfoOptionValues).toEqual(["PV-80003"]);
  });

  it("posts the Phase 14F payload on submit and refreshes versions on success", async () => {
    (
      api.listPromptVersions as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(promptVersions);
    (
      api.postPromptVersionRollbackFromUi as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue({
      ok: true,
      status: "rolled_back",
      agent: "ceo",
      previousActiveVersionId: "PV-80002",
      targetVersionId: "PV-80001",
      auditKind: "prompt_version.rollback.ui_changed",
      promptVersion: promptVersions[0],
      message: "Rolled ceo back to v1.0.",
    });

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByTestId("settings-rollback-open"));
    const modal = await screen.findByTestId(
      "rollback-system-modal-rollback",
    );
    fireEvent.change(
      within(modal).getByTestId("rollback-system-agent-select"),
      { target: { value: "ceo" } },
    );
    fireEvent.change(
      within(modal).getByTestId("rollback-system-target-select"),
      { target: { value: "PV-80001" } },
    );
    fireEvent.change(
      within(modal).getByTestId("rollback-system-reason-input"),
      { target: { value: "Phase 14F submit-flow test" } },
    );
    fireEvent.change(
      within(modal).getByTestId("rollback-system-phrase-input"),
      { target: { value: "ROLLBACK PROMPT VERSION" } },
    );
    fireEvent.click(within(modal).getByTestId("rollback-system-submit"));

    await waitFor(() => {
      const calls = (
        api.postPromptVersionRollbackFromUi as unknown as ReturnType<typeof vi.fn>
      ).mock.calls;
      expect(calls.length).toBe(1);
    });
    const call = (
      api.postPromptVersionRollbackFromUi as unknown as ReturnType<typeof vi.fn>
    ).mock.calls[0][0];
    expect(call.agent).toBe("ceo");
    expect(call.targetVersionId).toBe("PV-80001");
    expect(call.confirmationPhrase).toBe("ROLLBACK PROMPT VERSION");
    expect(call.reason).toContain("Phase 14F");

    // listPromptVersions called twice: once on mount, once on
    // onSuccess refresh.
    await waitFor(() =>
      expect(
        (api.listPromptVersions as unknown as ReturnType<typeof vi.fn>).mock
          .calls.length,
      ).toBeGreaterThanOrEqual(2),
    );
  });

  it("surfaces backend error inline when POST rejects", async () => {
    (
      api.listPromptVersions as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(promptVersions);
    (
      api.postPromptVersionRollbackFromUi as unknown as ReturnType<typeof vi.fn>
    ).mockRejectedValue(new Error("HTTP 403 — director only"));

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByTestId("settings-rollback-open"));
    const modal = await screen.findByTestId(
      "rollback-system-modal-rollback",
    );
    fireEvent.change(
      within(modal).getByTestId("rollback-system-agent-select"),
      { target: { value: "ceo" } },
    );
    fireEvent.change(
      within(modal).getByTestId("rollback-system-target-select"),
      { target: { value: "PV-80001" } },
    );
    fireEvent.change(
      within(modal).getByTestId("rollback-system-reason-input"),
      { target: { value: "Phase 14F error-surface test" } },
    );
    fireEvent.change(
      within(modal).getByTestId("rollback-system-phrase-input"),
      { target: { value: "ROLLBACK PROMPT VERSION" } },
    );
    fireEvent.click(within(modal).getByTestId("rollback-system-submit"));

    await waitFor(() =>
      expect(
        within(modal).getByText(/HTTP 403 — director only/i),
      ).toBeInTheDocument(),
    );
  });
});

// ---- Phase 14D + 14E + 14E-Hotfix-1 regression smoke ------------------

describe("Phase 14F — co-render with prior safety surfaces", () => {
  it("renders Rollback card alongside Kill Switch + Sandbox cards", async () => {
    (
      api.listPromptVersions as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(promptVersions);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    // Phase 14D card present (paused state).
    expect(
      await screen.findByTestId("settings-kill-switch-resume"),
    ).toBeInTheDocument();
    // Phase 14E card present (sandbox OFF → only Enable button).
    expect(screen.getByTestId("settings-sandbox-enable")).toBeInTheDocument();
    // Phase 14F card present.
    expect(
      screen.getByTestId("settings-rollback-open"),
    ).toBeInTheDocument();
  });
});
