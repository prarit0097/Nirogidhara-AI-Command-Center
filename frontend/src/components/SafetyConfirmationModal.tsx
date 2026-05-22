/**
 * Phase 14E — generic typed-phrase + reason confirmation modal.
 *
 * Refactored out of the Phase 14D KillSwitchModal so the sandbox-mode
 * surface can reuse the exact same UX guarantees:
 *   - Reason textarea (configurable min length, default 10 chars).
 *   - Exact typed confirmation phrase (case-sensitive full match).
 *   - Submit disabled until both inputs are valid.
 *   - Busy state during the async submit.
 *   - Backend error surfaced via toast + inline panel.
 *   - On success the parent's onSuccess callback fires.
 *
 * Phase 14D's KillSwitchModal is now a thin wrapper around this
 * component (testids are preserved exactly so Phase 14D tests
 * continue to pass). Phase 14E's SandboxModeModal is another wrapper.
 *
 * Hard rule: this component is presentation-only. It NEVER calls a
 * provider directly — it invokes the caller-supplied async
 * ``onConfirm(reason)`` handler which owns the api.postSaas... call.
 */
import { useEffect, useState, type ReactNode } from "react";
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

export interface SafetyConfirmationModalProps {
  open: boolean;
  onOpenChange: (next: boolean) => void;
  /** Modal heading shown at the top. */
  title: string;
  /** Long-form impact description shown under the title. */
  description: ReactNode;
  /** Exact phrase the operator must type to enable the submit button. */
  confirmationPhrase: string;
  /** Submit button label. */
  submitLabel: string;
  /** Toast message shown after a successful POST. */
  successMessage: string;
  /** Submit button variant — danger actions use "destructive". */
  submitVariant?: "destructive" | "default";
  /** Minimum reason length in characters. Default 10. */
  minReasonLength?: number;
  /**
   * Prefix for every data-testid the modal renders. Phase 14D consumers
   * pass "kill-switch"; Phase 14E sandbox consumer passes "sandbox-mode";
   * Phase 14F rollback consumer passes "rollback-system".
   */
  testIdPrefix: string;
  /** Stable identifier appended to the modal-root testid (per-action). */
  actionKey: string;
  /** Caller-owned async POST. Receives the typed reason. */
  onConfirm: (reason: string) => Promise<void>;
  /**
   * Phase 14F — optional ReactNode rendered between the description
   * and the reason/phrase block. The rollback modal uses this slot
   * to mount its agent + target-version selectors. The parent owns
   * the selector state and the validation predicate.
   */
  extraInputs?: ReactNode;
  /**
   * Phase 14F — additional precondition the parent enforces (e.g.
   * "an agent and target version must both be selected"). When
   * provided and false, submit stays disabled even if reason +
   * phrase are valid.
   */
  extraValid?: boolean;
}

export function SafetyConfirmationModal({
  open,
  onOpenChange,
  title,
  description,
  confirmationPhrase,
  submitLabel,
  successMessage,
  submitVariant = "destructive",
  minReasonLength = 10,
  testIdPrefix,
  actionKey,
  onConfirm,
  extraInputs,
  extraValid = true,
}: SafetyConfirmationModalProps) {
  const [reason, setReason] = useState("");
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Phase 14E — reset the form whenever the modal opens or the
  // action key changes so a fresh confirmation flow does not inherit
  // stale text.
  useEffect(() => {
    if (open) {
      setReason("");
      setTyped("");
      setError(null);
    }
  }, [open, actionKey]);

  const reasonValid = reason.trim().length >= minReasonLength;
  const phraseValid = typed === confirmationPhrase;
  const canSubmit = reasonValid && phraseValid && extraValid && !busy;

  const onSubmit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm(reason.trim());
      onOpenChange(false);
      toast.success(successMessage);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Action failed.";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent data-testid={`${testIdPrefix}-modal-${actionKey}`}>
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {/* Phase 14F — optional selectors (e.g. rollback agent +
              target version) injected by the caller. Rendered above
              the reason + phrase block so the operator picks the
              target first. */}
          {extraInputs}
          <label className="block">
            <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Reason (audit-logged)
            </span>
            <textarea
              data-testid={`${testIdPrefix}-reason-input`}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              disabled={busy}
              rows={2}
              minLength={minReasonLength}
              placeholder={`At least ${minReasonLength} characters — e.g. "Compliance incident drill"`}
              className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-2 focus:ring-ring/20"
            />
            {!reasonValid && reason.length > 0 && (
              <span className="text-[11px] text-warning">
                Reason must be at least {minReasonLength} characters.
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
                {confirmationPhrase}
              </code>{" "}
              exactly
            </span>
            <input
              data-testid={`${testIdPrefix}-phrase-input`}
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              disabled={busy}
              placeholder={confirmationPhrase}
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
            data-testid={`${testIdPrefix}-submit`}
            variant={submitVariant}
            onClick={onSubmit}
            disabled={!canSubmit}
          >
            {busy ? "Working…" : submitLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default SafetyConfirmationModal;
