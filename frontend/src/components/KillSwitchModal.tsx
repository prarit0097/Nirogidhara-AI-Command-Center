/**
 * Phase 14D — AI Kill Switch confirmation modal.
 *
 * Shared component used by both the Topbar emergency-stop button and the
 * Settings page kill-switch card. Enforces:
 *   - Operator-typed reason (>= 10 chars).
 *   - Exact typed confirmation phrase per action
 *     (ACTIVATE KILL SWITCH / RESUME AI OPERATIONS).
 *   - Submit disabled until both are valid.
 *   - Backend POST via api.postSaasRuntimeLiveGateKillSwitch; refreshes
 *     state on success; surfaces backend error message safely on failure.
 *
 * The component does NOT call any provider directly — it only hits the
 * Phase 6H/14D /api/v1/saas/runtime-live-gate/kill-switch/ endpoint.
 */
import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { api } from "@/services/api";
import type {
  SaasRuntimeLiveGateKillSwitch,
  SaasRuntimeLiveGateKillSwitchAction,
} from "@/types/domain";

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

const MIN_REASON_LENGTH = 10;

export function KillSwitchModal({
  open,
  onOpenChange,
  action,
  expectedPhrase,
  onSuccess,
}: KillSwitchModalProps) {
  const [reason, setReason] = useState("");
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const phrase = expectedPhrase ?? PHRASE_BY_ACTION[action];

  // Phase 14D — reset form whenever the modal opens or the action changes
  // so a fresh confirmation flow does not inherit stale text.
  useEffect(() => {
    if (open) {
      setReason("");
      setTyped("");
      setError(null);
    }
  }, [open, action]);

  const reasonValid = reason.trim().length >= MIN_REASON_LENGTH;
  const phraseValid = typed === phrase;
  const canSubmit = reasonValid && phraseValid && !busy;

  const onSubmit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      const next = await api.postSaasRuntimeLiveGateKillSwitch({
        action,
        reason: reason.trim(),
        confirmationPhrase: typed,
      });
      onSuccess?.(next);
      onOpenChange(false);
      toast.success(
        action === "activate_emergency_stop"
          ? "AI Kill Switch engaged — automated agents paused"
          : "AI operations resumed — daily agent sweeps allowed",
      );
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Kill switch action failed.";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent data-testid={`kill-switch-modal-${action}`}>
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">
            {TITLE_BY_ACTION[action]}
          </DialogTitle>
          <DialogDescription>{IMPACT_BY_ACTION[action]}</DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <label className="block">
            <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Reason (audit-logged)
            </span>
            <textarea
              data-testid="kill-switch-reason-input"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              disabled={busy}
              rows={2}
              minLength={MIN_REASON_LENGTH}
              placeholder={`At least ${MIN_REASON_LENGTH} characters — e.g. "Compliance incident drill"`}
              className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-2 focus:ring-ring/20"
            />
            {!reasonValid && reason.length > 0 && (
              <span className="text-[11px] text-warning">
                Reason must be at least {MIN_REASON_LENGTH} characters.
              </span>
            )}
          </label>

          <label className="block">
            <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Confirmation phrase
            </span>
            <span className="ml-2 text-[11px] text-muted-foreground">
              type{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 font-mono">
                {phrase}
              </code>{" "}
              exactly
            </span>
            <input
              data-testid="kill-switch-phrase-input"
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              disabled={busy}
              placeholder={phrase}
              autoComplete="off"
              spellCheck={false}
              className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm font-mono focus:border-ring focus:outline-none focus:ring-2 focus:ring-ring/20"
            />
          </label>

          {error && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
              {error}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={busy}
          >
            Cancel
          </Button>
          <Button
            data-testid="kill-switch-submit"
            variant={action === "activate_emergency_stop" ? "destructive" : "default"}
            onClick={onSubmit}
            disabled={!canSubmit}
          >
            {busy ? "Working…" : SUBMIT_LABEL[action]}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default KillSwitchModal;
