/**
 * Phase 14E — Sandbox Mode confirmation modal.
 *
 * Thin wrapper around the generic SafetyConfirmationModal. Calls
 * api.postAiSandboxModeAction on confirm. Testids:
 *   - sandbox-mode-modal-${action}
 *   - sandbox-mode-reason-input
 *   - sandbox-mode-phrase-input
 *   - sandbox-mode-submit
 */
import { api } from "@/services/api";
import type {
  AiSandboxModeAction,
  AiSandboxModeStatus,
} from "@/types/domain";
import SafetyConfirmationModal from "@/components/SafetyConfirmationModal";

export interface SandboxModeModalProps {
  open: boolean;
  onOpenChange: (next: boolean) => void;
  action: AiSandboxModeAction;
  /** Optional: caller-known expected phrase (backend re-validates). */
  expectedPhrase?: string;
  onSuccess?: (next: AiSandboxModeStatus) => void;
}

const PHRASE_BY_ACTION: Record<AiSandboxModeAction, string> = {
  enable_sandbox_mode: "ENABLE SANDBOX MODE",
  disable_sandbox_mode: "DISABLE SANDBOX MODE",
};

const TITLE_BY_ACTION: Record<AiSandboxModeAction, string> = {
  enable_sandbox_mode: "Enable Sandbox Mode?",
  disable_sandbox_mode: "Disable Sandbox Mode?",
};

const IMPACT_BY_ACTION: Record<AiSandboxModeAction, string> = {
  enable_sandbox_mode:
    "Enabling sandbox mode stamps every successful AgentRun with sandbox_mode=true and routes the CEO success path away from CeoBriefing refresh. AI agents still execute end-to-end and the audit ledger still writes — but visible business-state mutations from AI paths are suppressed.",
  disable_sandbox_mode:
    "Disabling sandbox mode returns AI agents to live business-state mutation behavior. This action is a Phase 4C director_override and is matrix-gated server-side; only a director may disable. Use only after confirming new prompts/playbooks have passed shadow-mode review.",
};

const SUBMIT_LABEL: Record<AiSandboxModeAction, string> = {
  enable_sandbox_mode: "Enable Sandbox Mode",
  disable_sandbox_mode: "Disable Sandbox Mode",
};

const SUCCESS_MESSAGE: Record<AiSandboxModeAction, string> = {
  enable_sandbox_mode:
    "Sandbox Mode enabled — AI runs are now shadow-mode",
  disable_sandbox_mode:
    "Sandbox Mode disabled — AI runs back to live business behavior",
};

export function SandboxModeModal({
  open,
  onOpenChange,
  action,
  expectedPhrase,
  onSuccess,
}: SandboxModeModalProps) {
  const phrase = expectedPhrase ?? PHRASE_BY_ACTION[action];

  return (
    <SafetyConfirmationModal
      open={open}
      onOpenChange={onOpenChange}
      title={TITLE_BY_ACTION[action]}
      description={IMPACT_BY_ACTION[action]}
      confirmationPhrase={phrase}
      submitLabel={SUBMIT_LABEL[action]}
      successMessage={SUCCESS_MESSAGE[action]}
      submitVariant={action === "disable_sandbox_mode" ? "destructive" : "default"}
      testIdPrefix="sandbox-mode"
      actionKey={action}
      onConfirm={async (reason: string) => {
        const next = await api.postAiSandboxModeAction({
          action,
          reason,
          confirmationPhrase: phrase,
        });
        onSuccess?.(next);
      }}
    />
  );
}

export default SandboxModeModal;
