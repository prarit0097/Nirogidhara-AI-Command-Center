/**
 * Phase 14E — frontend tests for the Sandbox Mode UI wiring.
 *
 * Covers:
 *   - Settings page renders real sandbox status (Sandbox ON / OFF).
 *   - Enable button enabled only while sandbox is OFF; Disable button
 *     enabled only while sandbox is ON.
 *   - Enable click opens the enable_sandbox_mode modal.
 *   - Disable click opens the disable_sandbox_mode modal.
 *   - Modal submit disabled until reason >= 10 chars AND exact phrase.
 *   - Exact phrase swap (typing the disable phrase under enable action)
 *     keeps submit disabled.
 *   - Successful POST refreshes UI from the returned state.
 *   - API error surfaces a safe error message via toast.
 *   - No "(mock)" text remains for Sandbox Mode.
 *   - Phase 14D kill-switch surface still renders alongside (regression).
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

const sandboxOn = {
  ...sandboxOff,
  isEnabled: true,
  sandboxEnabled: true,
  statusLabel: "enabled" as const,
  reason: "Shadow-mode review of new prompt v3.3",
  updatedBy: "phase14e_director",
  updatedAt: "2026-05-22T10:00:00Z",
};

const killSwitchPaused = {
  scope: "global",
  enabled: true,
  runtimeKillSwitchEnabled: true,
  aiExecutionBlocked: true,
  statusLabel: "paused" as const,
  reason: "Production state",
  updatedAt: null,
  updatedBy: "",
  dryRun: true,
  liveExecutionAllowed: false,
  externalCallWillBeMade: false,
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
};

beforeEach(() => {
  vi.clearAllMocks();
  seedSettingsMock();
});

// ---- Settings sandbox card --------------------------------------------

describe("Phase 14E — Settings Sandbox Mode card", () => {
  it("renders 'Sandbox OFF' status with ONLY the Enable button (Phase 14E-Hotfix-1)", async () => {
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOff);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    // Enable IS rendered.
    const enableBtn = (await screen.findByTestId(
      "settings-sandbox-enable",
    )) as HTMLButtonElement;
    expect(enableBtn.disabled).toBe(false);
    // Disable is NOT rendered while Sandbox is OFF.
    expect(screen.queryByTestId("settings-sandbox-disable")).toBeNull();
    expect(screen.getByText(/Sandbox OFF/i)).toBeInTheDocument();
  });

  it("renders 'Sandbox ON' status with ONLY the Disable button (Phase 14E-Hotfix-1)", async () => {
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOn);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    // Disable IS rendered.
    const disableBtn = (await screen.findByTestId(
      "settings-sandbox-disable",
    )) as HTMLButtonElement;
    expect(disableBtn.disabled).toBe(false);
    // Enable is NOT rendered while Sandbox is ON.
    expect(screen.queryByTestId("settings-sandbox-enable")).toBeNull();
    expect(screen.getByText(/Sandbox ON/i)).toBeInTheDocument();
    // Last reason should surface so the operator sees who flipped it.
    expect(
      screen.getByText(/Shadow-mode review of new prompt v3.3/),
    ).toBeInTheDocument();
  });

  it("opens the enable_sandbox_mode modal when Enable is clicked", async () => {
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOff);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByTestId("settings-sandbox-enable"));
    expect(
      await screen.findByTestId("sandbox-mode-modal-enable_sandbox_mode"),
    ).toBeInTheDocument();
  });

  it("opens the disable_sandbox_mode modal when Disable is clicked", async () => {
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOn);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByTestId("settings-sandbox-disable"));
    expect(
      await screen.findByTestId("sandbox-mode-modal-disable_sandbox_mode"),
    ).toBeInTheDocument();
  });

  it("does not surface any '(mock)' text for Sandbox Mode", async () => {
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOff);

    const { container } = render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );
    await screen.findByTestId("settings-sandbox-enable");
    expect(container.textContent).not.toMatch(
      /Sandbox Mode[^.]*\(mock\)/i,
    );
  });
});

// ---- Sandbox modal validation -----------------------------------------

describe("Phase 14E — SandboxModeModal validation", () => {
  it("submit disabled until reason length AND exact enable phrase", async () => {
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOff);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByTestId("settings-sandbox-enable"));

    const modal = await screen.findByTestId(
      "sandbox-mode-modal-enable_sandbox_mode",
    );
    const submit = within(modal).getByTestId(
      "sandbox-mode-submit",
    ) as HTMLButtonElement;
    const reasonInput = within(modal).getByTestId(
      "sandbox-mode-reason-input",
    ) as HTMLTextAreaElement;
    const phraseInput = within(modal).getByTestId(
      "sandbox-mode-phrase-input",
    ) as HTMLInputElement;

    expect(submit.disabled).toBe(true);
    fireEvent.change(reasonInput, { target: { value: "short" } });
    expect(submit.disabled).toBe(true);

    fireEvent.change(phraseInput, {
      target: { value: "ENABLE SANDBOX MODE" },
    });
    expect(submit.disabled).toBe(true); // reason still too short

    fireEvent.change(reasonInput, {
      target: { value: "Phase 14E enable drill — shadow new prompts" },
    });
    expect(submit.disabled).toBe(false);

    // Phrase swap (disable phrase under enable action) → submit re-disabled.
    fireEvent.change(phraseInput, {
      target: { value: "DISABLE SANDBOX MODE" },
    });
    expect(submit.disabled).toBe(true);
  });

  it("posts to the backend and refreshes UI on success", async () => {
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOff);
    (
      api.postAiSandboxModeAction as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOn);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByTestId("settings-sandbox-enable"));

    const modal = await screen.findByTestId(
      "sandbox-mode-modal-enable_sandbox_mode",
    );
    fireEvent.change(within(modal).getByTestId("sandbox-mode-reason-input"), {
      target: { value: "Phase 14E end-to-end happy path" },
    });
    fireEvent.change(within(modal).getByTestId("sandbox-mode-phrase-input"), {
      target: { value: "ENABLE SANDBOX MODE" },
    });
    fireEvent.click(within(modal).getByTestId("sandbox-mode-submit"));

    await waitFor(() => {
      expect(
        (api.postAiSandboxModeAction as unknown as ReturnType<typeof vi.fn>)
          .mock.calls.length,
      ).toBe(1);
    });
    const call = (
      api.postAiSandboxModeAction as unknown as ReturnType<typeof vi.fn>
    ).mock.calls[0][0];
    expect(call.action).toBe("enable_sandbox_mode");
    expect(call.confirmationPhrase).toBe("ENABLE SANDBOX MODE");
    expect(call.reason).toContain("Phase 14E");

    // After success the card should re-render with the Sandbox ON state.
    await waitFor(() =>
      expect(screen.getByText(/Sandbox ON/i)).toBeInTheDocument(),
    );
  });

  it("surfaces an inline error message when the API rejects", async () => {
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOff);
    (
      api.postAiSandboxModeAction as unknown as ReturnType<typeof vi.fn>
    ).mockRejectedValue(new Error("HTTP 403 — director only"));

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByTestId("settings-sandbox-enable"));

    const modal = await screen.findByTestId(
      "sandbox-mode-modal-enable_sandbox_mode",
    );
    fireEvent.change(within(modal).getByTestId("sandbox-mode-reason-input"), {
      target: { value: "Phase 14E error-surface test" },
    });
    fireEvent.change(within(modal).getByTestId("sandbox-mode-phrase-input"), {
      target: { value: "ENABLE SANDBOX MODE" },
    });
    fireEvent.click(within(modal).getByTestId("sandbox-mode-submit"));

    await waitFor(() =>
      expect(
        within(modal).getByText(/HTTP 403 — director only/i),
      ).toBeInTheDocument(),
    );
  });
});

// ---- Phase 14D regression smoke ---------------------------------------

describe("Phase 14E — Phase 14D kill-switch surface still works", () => {
  it("renders the kill-switch card alongside the sandbox card", async () => {
    (
      api.getAiSandboxModeStatus as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(sandboxOff);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    // Both cards must exist on the same Settings render.
    expect(
      await screen.findByTestId("settings-kill-switch-activate"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("settings-sandbox-enable"),
    ).toBeInTheDocument();
  });
});
