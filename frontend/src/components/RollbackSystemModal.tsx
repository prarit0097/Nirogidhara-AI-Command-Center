/**
 * Phase 14F — Prompt Version rollback confirmation modal.
 *
 * Wraps the generic SafetyConfirmationModal (Phase 14E refactor) with
 * agent + target-version selectors that mount in the `extraInputs`
 * slot. The actual POST hits the Phase 14F-specific endpoint
 * /api/ai/prompt-versions/rollback-from-ui/ which is gated by the
 * typed phrase "ROLLBACK PROMPT VERSION" + reason >= 10 chars +
 * admin/director permission.
 *
 * The modal renders ONLY safe metadata for each candidate version
 * (id, agent, version label, status, createdAt, createdBy if
 * available). It deliberately does NOT render `systemPolicy` or
 * `rolePrompt` body text — the Phase 14F UI surface only needs
 * version metadata to identify the rollback target.
 *
 * Testids: rollback-system-modal-rollback, rollback-system-agent-select,
 * rollback-system-target-select, rollback-system-reason-input,
 * rollback-system-phrase-input, rollback-system-submit.
 */
import { useEffect, useMemo, useState } from "react";
import { api } from "@/services/api";
import type {
  PromptVersion,
  PromptVersionRollbackFromUiResult,
} from "@/types/domain";
import SafetyConfirmationModal from "@/components/SafetyConfirmationModal";

export interface RollbackSystemModalProps {
  open: boolean;
  onOpenChange: (next: boolean) => void;
  /**
   * Caller-supplied list of all visible prompt versions. The modal
   * filters this list to the rollback-eligible candidates (status
   * archived / rolled_back / sandbox — i.e. not the currently
   * active version of the selected agent).
   */
  versions: PromptVersion[];
  /** Optional pre-selected agent (e.g. when opened from an agent row). */
  initialAgent?: string;
  /** Called with the fresh result after a successful POST. */
  onSuccess?: (result: PromptVersionRollbackFromUiResult) => void;
}

const CONFIRMATION_PHRASE = "ROLLBACK PROMPT VERSION";

const IMPACT_DESCRIPTION =
  "This changes the active prompt/playbook version used by the selected AI agent. " +
  "This does not resume AI, toggle sandbox, send messages, call customers, " +
  "collect payments, or dispatch shipments.";

export function RollbackSystemModal({
  open,
  onOpenChange,
  versions,
  initialAgent,
  onSuccess,
}: RollbackSystemModalProps) {
  // Local state — selectors live in this component so the parent
  // doesn't need to know about Phase 14F's payload shape.
  const [agent, setAgent] = useState<string>(initialAgent ?? "");
  const [targetVersionId, setTargetVersionId] = useState<string>("");

  // Phase 14F — reset selectors whenever the modal opens.
  useEffect(() => {
    if (open) {
      setAgent(initialAgent ?? "");
      setTargetVersionId("");
    }
  }, [open, initialAgent]);

  // Group versions by agent for the agent selector. Only agents that
  // have at least one rollback-eligible candidate appear in the list.
  const agentsWithCandidates = useMemo(() => {
    const set = new Set<string>();
    versions.forEach((v) => {
      // Eligible candidate = exists, is NOT the currently active row
      // for that agent. The backend enforces the same constraint.
      if (!v.isActive) set.add(v.agent);
    });
    return Array.from(set).sort();
  }, [versions]);

  // Target versions filtered by the selected agent + excluding the
  // currently-active row.
  const targetCandidates = useMemo(() => {
    if (!agent) return [] as PromptVersion[];
    return versions
      .filter((v) => v.agent === agent && !v.isActive)
      .sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1));
  }, [agent, versions]);

  const extraValid = Boolean(agent && targetVersionId);

  return (
    <SafetyConfirmationModal
      open={open}
      onOpenChange={onOpenChange}
      title="Rollback prompt version?"
      description={IMPACT_DESCRIPTION}
      confirmationPhrase={CONFIRMATION_PHRASE}
      submitLabel="Roll back prompt version"
      successMessage="Prompt version rolled back"
      submitVariant="destructive"
      testIdPrefix="rollback-system"
      actionKey="rollback"
      extraValid={extraValid}
      extraInputs={
        <>
          <label className="block">
            <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              AI agent
            </span>
            <select
              data-testid="rollback-system-agent-select"
              value={agent}
              onChange={(event) => {
                setAgent(event.target.value);
                setTargetVersionId("");
              }}
              className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-2 focus:ring-ring/20"
            >
              <option value="">Select an agent…</option>
              {agentsWithCandidates.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
            {agentsWithCandidates.length === 0 && (
              <span className="text-[11px] text-muted-foreground">
                No rollback candidates available — only the currently active
                version exists for every agent.
              </span>
            )}
          </label>

          <label className="block">
            <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Target version (rollback to)
            </span>
            <select
              data-testid="rollback-system-target-select"
              value={targetVersionId}
              onChange={(event) => setTargetVersionId(event.target.value)}
              disabled={!agent || targetCandidates.length === 0}
              className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-2 focus:ring-ring/20 disabled:bg-muted/40"
            >
              <option value="">
                {agent ? "Select a target version…" : "Select an agent first"}
              </option>
              {targetCandidates.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.version}
                  {v.title ? ` — ${v.title}` : ""}
                  {" · "}
                  {v.status}
                  {v.createdBy ? ` · by ${v.createdBy}` : ""}
                </option>
              ))}
            </select>
          </label>
        </>
      }
      onConfirm={async (reason: string) => {
        const result = await api.postPromptVersionRollbackFromUi({
          agent,
          targetVersionId,
          reason,
          confirmationPhrase: CONFIRMATION_PHRASE,
        });
        onSuccess?.(result);
      }}
    />
  );
}

export default RollbackSystemModal;
