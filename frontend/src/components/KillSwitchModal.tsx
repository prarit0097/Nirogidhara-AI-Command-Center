/**
 * Phase 14D — AI Kill Switch confirmation modal.
 *
 * Phase 14E refactor: this is now a thin wrapper around the generic
 * SafetyConfirmationModal so the sandbox-mode surface can reuse the
 * same UX guarantees. Testids ("kill-switch-modal-${action}",
 * "kill-switch-reason-input", "kill-switch-phrase-input",
 * "kill-switch-submit") are preserved exactly — Phase 14D tests stay
 * green.
 */
import { api } from "@/services/api";
import type {
  SaasRuntimeLiveGateKillSwitch,
  SaasRuntimeLiveGateKillSwitchAction,
} from "@/types/domain";
import SafetyConfirmationModal from "@/components/SafetyConfirmationModal";

export interface KillSwitchModalProps {
  open: boolean;
  onOpenChange: (next: boolean) => void;
  action: SaasRuntimeLiveGateKillSwitchAction;
  /** Optional: caller-known expected phrase (falls back to the canonical
   * Phase 14D constant; the backend re-validates regardless). */
  expectedPhrase?: string;
  /** Called with the fresh backend snapshot after a successful POST. */
  onSuccess?: (next: SaasRuntimeLiveGateKillSwitch) => void;
}

const PHRASE_BY_ACTION: Record<
  SaasRuntimeLiveGateKillSwitchAction,
  string
> = {
  activate_emergency_stop: "ACTIVATE KILL SWITCH",
  resume_ai_operations: "RESUME AI OPERATIONS",
};

const TITLE_BY_ACTION: Record<
  SaasRuntimeLiveGateKillSwitchAction,
  string
> = {
  activate_emergency_stop: "Activate AI Kill Switch?",
  resume_ai_operations: "Resume AI Operations?",
};

const IMPACT_BY_ACTION: Record<
  SaasRuntimeLiveGateKillSwitchAction,
  string
> = {
  activate_emergency_stop:
    "This will immediately PAUSE all automated AI agents (daily snapshot sweeps + Phase 7+/12A execute gates). Human-operated CLI workflows continue. Use only during an incident or compliance event. The action is fully reversible via Resume.",
  resume_ai_operations:
    "This will RESUME all automated AI agents — daily snapshot sweeps + execute-gate readiness will be allowed again. Use only after confirming the incident or compliance event is fully resolved.",
};

const SUBMIT_LABEL: Record<
  SaasRuntimeLiveGateKillSwitchAction,
  string
> = {
  activate_emergency_stop: "Engage Kill Switch",
  resume_ai_operations: "Resume AI Operations",
};

const SUCCESS_MESSAGE: Record<
  SaasRuntimeLiveGateKillSwitchAction,
  string
> = {
  activate_emergency_stop:
    "AI Kill Switch engaged — automated agents paused",
  resume_ai_operations:
    "AI operations resumed — daily agent sweeps allowed",
};

export function KillSwitchModal({
  open,
  onOpenChange,
  action,
  expectedPhrase,
  onSuccess,
}: KillSwitchModalProps) {
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
      submitVariant={action === "activate_emergency_stop" ? "destructive" : "default"}
      testIdPrefix="kill-switch"
      actionKey={action}
      onConfirm={async (reason: string) => {
        const next = await api.postSaasRuntimeLiveGateKillSwitch({
          action,
          reason,
          confirmationPhrase: phrase,
        });
        onSuccess?.(next);
      }}
    />
  );
}

export default KillSwitchModal;
