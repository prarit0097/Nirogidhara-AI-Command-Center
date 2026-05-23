/**
 * Phase 14D — frontend tests for the AI Kill Switch UI wiring.
 *
 * Covers:
 *   - Topbar loads real backend state and renders the right control:
 *       * `enabled=false` (AI Running) → red "AI Kill Switch" button.
 *       * `enabled=true` (AI Paused) → warning "AI Paused" indicator.
 *   - Topbar button click opens the activate-emergency-stop modal.
 *   - KillSwitchModal: submit disabled until reason (>= 10 chars)
 *     AND the exact typed confirmation phrase.
 *   - Settings page renders real state + activate/resume buttons
 *     gated by current state.
 *   - Successful POST refreshes the on-screen state.
 *   - No "(mock)" text remains for AI Kill Switch.
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
import { Topbar } from "@/components/layout/Topbar";
import Settings from "@/pages/Settings";
import { SafetyStateProvider } from "@/context/SafetyStateContext";

// ---- api mock ----------------------------------------------------------

vi.mock("@/services/api", () => ({
  api: {
    getSaasRuntimeLiveGateKillSwitch: vi.fn(),
    postSaasRuntimeLiveGateKillSwitch: vi.fn(),
    getSettingsMock: vi.fn(),
    getWhatsAppProviderStatus: vi.fn(),
    // Phase 15D — Topbar safety pill also fetches sandbox + briefing
    // statuses on mount. Provide deterministic stubs so the pill
    // never throws on undefined.then(); the kill-switch button under
    // test is unaffected by these.
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
    // OrgBadge (rendered inside Topbar) hits this on mount; satisfy it
    // with a deterministic shape so the Topbar render does not throw.
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

const runningState = {
  scope: "global",
  enabled: false,
  runtimeKillSwitchEnabled: false,
  aiExecutionBlocked: false,
  statusLabel: "running" as const,
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
  confirmationPhrases: {
    activateEmergencyStop: "ACTIVATE KILL SWITCH",
    resumeAiOperations: "RESUME AI OPERATIONS",
  },
};

const pausedState = {
  ...runningState,
  enabled: true,
  runtimeKillSwitchEnabled: true,
  aiExecutionBlocked: true,
  statusLabel: "paused" as const,
  killSwitchActive: true,
  reason: "Compliance drill",
  updatedBy: "phase14d_admin",
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
};

beforeEach(() => {
  vi.clearAllMocks();
  seedSettingsMock();
});

// ---- Topbar ------------------------------------------------------------

describe("Phase 14D — Topbar AI Kill Switch", () => {
  it("renders the red 'AI Kill Switch' button when backend says AI is running", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(runningState);

    render(
      <MemoryRouter>
        <SafetyStateProvider>
          <Topbar onMenu={() => {}} />
        </SafetyStateProvider>
      </MemoryRouter>,
    );

    const button = await screen.findByTestId("topbar-kill-switch-button");
    expect(button).toBeInTheDocument();
    expect(screen.queryByTestId("topbar-kill-switch-paused")).toBeNull();
  });

  it("renders the 'AI Paused' indicator when backend says AI is paused", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(pausedState);

    render(
      <MemoryRouter>
        <SafetyStateProvider>
          <Topbar onMenu={() => {}} />
        </SafetyStateProvider>
      </MemoryRouter>,
    );

    expect(
      await screen.findByTestId("topbar-kill-switch-paused"),
    ).toBeInTheDocument();
    // Click-to-activate button must NOT render when paused — resume is
    // intentionally surfaced only from /settings.
    expect(screen.queryByTestId("topbar-kill-switch-button")).toBeNull();
  });

  it("opens the activate_emergency_stop modal when the Topbar button is clicked", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(runningState);

    render(
      <MemoryRouter>
        <SafetyStateProvider>
          <Topbar onMenu={() => {}} />
        </SafetyStateProvider>
      </MemoryRouter>,
    );

    const button = await screen.findByTestId("topbar-kill-switch-button");
    fireEvent.click(button);

    expect(
      await screen.findByTestId(
        "kill-switch-modal-activate_emergency_stop",
      ),
    ).toBeInTheDocument();
  });

  it("does not surface any '(mock)' text for the kill switch", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(runningState);

    const { container } = render(
      <MemoryRouter>
        <SafetyStateProvider>
          <Topbar onMenu={() => {}} />
        </SafetyStateProvider>
      </MemoryRouter>,
    );
    await screen.findByTestId("topbar-kill-switch-button");
    // The Phase 14D Topbar must not contain the legacy "(mock)" copy.
    expect(container.textContent).not.toMatch(/AI Kill Switch[^.]*\(mock\)/i);
  });
});

// ---- KillSwitchModal ---------------------------------------------------

describe("Phase 14D — KillSwitchModal validation", () => {
  it("disables submit until reason length AND exact phrase are met", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(runningState);

    render(
      <MemoryRouter>
        <SafetyStateProvider>
          <Topbar onMenu={() => {}} />
        </SafetyStateProvider>
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByTestId("topbar-kill-switch-button"));

    const modal = await screen.findByTestId(
      "kill-switch-modal-activate_emergency_stop",
    );
    const submit = within(modal).getByTestId(
      "kill-switch-submit",
    ) as HTMLButtonElement;
    const reasonInput = within(modal).getByTestId(
      "kill-switch-reason-input",
    ) as HTMLTextAreaElement;
    const phraseInput = within(modal).getByTestId(
      "kill-switch-phrase-input",
    ) as HTMLInputElement;

    // Initially disabled.
    expect(submit.disabled).toBe(true);

    // Reason too short → still disabled.
    fireEvent.change(reasonInput, { target: { value: "short" } });
    expect(submit.disabled).toBe(true);

    // Correct phrase but reason still too short.
    fireEvent.change(phraseInput, {
      target: { value: "ACTIVATE KILL SWITCH" },
    });
    expect(submit.disabled).toBe(true);

    // Reason ≥ 10 chars + correct phrase → submit enabled.
    fireEvent.change(reasonInput, {
      target: { value: "Phase 14D drill — compliance incident" },
    });
    expect(submit.disabled).toBe(false);

    // Break phrase → re-disable.
    fireEvent.change(phraseInput, {
      target: { value: "ACTIVATE KILL SWICH" },
    });
    expect(submit.disabled).toBe(true);
  });

  it("posts to the backend and refreshes state on success", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(runningState);
    (
      api.postSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(pausedState);

    render(
      <MemoryRouter>
        <SafetyStateProvider>
          <Topbar onMenu={() => {}} />
        </SafetyStateProvider>
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByTestId("topbar-kill-switch-button"));

    const modal = await screen.findByTestId(
      "kill-switch-modal-activate_emergency_stop",
    );
    fireEvent.change(
      within(modal).getByTestId("kill-switch-reason-input"),
      { target: { value: "Phase 14D test — activate" } },
    );
    fireEvent.change(within(modal).getByTestId("kill-switch-phrase-input"), {
      target: { value: "ACTIVATE KILL SWITCH" },
    });
    fireEvent.click(within(modal).getByTestId("kill-switch-submit"));

    await waitFor(() => {
      expect(
        (
          api.postSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<
            typeof vi.fn
          >
        ).mock.calls.length,
      ).toBe(1);
    });
    const call = (
      api.postSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<
        typeof vi.fn
      >
    ).mock.calls[0][0];
    expect(call.action).toBe("activate_emergency_stop");
    expect(call.confirmationPhrase).toBe("ACTIVATE KILL SWITCH");
    expect(call.reason).toContain("Phase 14D test");

    // After the success callback fires, Topbar should swap to the
    // paused indicator.
    await waitFor(() =>
      expect(
        screen.queryByTestId("topbar-kill-switch-paused"),
      ).toBeInTheDocument(),
    );
  });
});

// ---- Settings page -----------------------------------------------------

describe("Phase 14D — Settings AI Kill Switch card", () => {
  it("renders the real backend state and gates the action buttons", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(runningState);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    // Activate is enabled while running; Resume is disabled.
    const activate = (await screen.findByTestId(
      "settings-kill-switch-activate",
    )) as HTMLButtonElement;
    const resume = screen.getByTestId(
      "settings-kill-switch-resume",
    ) as HTMLButtonElement;
    expect(activate.disabled).toBe(false);
    expect(resume.disabled).toBe(true);

    // Phase 14D copy: "AI Running"
    expect(screen.getByText(/AI Running/i)).toBeInTheDocument();
  });

  it("requires the exact resume phrase before submit is enabled", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(pausedState);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );

    const resume = (await screen.findByTestId(
      "settings-kill-switch-resume",
    )) as HTMLButtonElement;
    expect(resume.disabled).toBe(false);
    fireEvent.click(resume);

    const modal = await screen.findByTestId(
      "kill-switch-modal-resume_ai_operations",
    );
    const submit = within(modal).getByTestId(
      "kill-switch-submit",
    ) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);

    // Wrong phrase first.
    fireEvent.change(within(modal).getByTestId("kill-switch-reason-input"), {
      target: { value: "Incident resolved; resume" },
    });
    fireEvent.change(within(modal).getByTestId("kill-switch-phrase-input"), {
      target: { value: "ACTIVATE KILL SWITCH" }, // wrong phrase for resume
    });
    expect(submit.disabled).toBe(true);

    // Correct resume phrase.
    fireEvent.change(within(modal).getByTestId("kill-switch-phrase-input"), {
      target: { value: "RESUME AI OPERATIONS" },
    });
    expect(submit.disabled).toBe(false);
  });

  it("does not surface any '(mock)' text in the AI Kill Switch card", async () => {
    (
      api.getSaasRuntimeLiveGateKillSwitch as unknown as ReturnType<typeof vi.fn>
    ).mockResolvedValue(runningState);

    const { container } = render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );
    await screen.findByTestId("settings-kill-switch-activate");
    expect(container.textContent).not.toMatch(
      /AI Kill Switch[^.]*\(mock\)/i,
    );
  });
});
