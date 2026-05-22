/**
 * Phase 15A — read-only Prompt Version Rollback History modal.
 *
 * Opened from the Settings Rollback System card via the new
 * "View rollback history" secondary button. Renders sanitised
 * Phase 14F UI audit rows + Phase 3D service audit rows.
 *
 * Hard guarantees:
 *   - NEVER renders system_policy / role_prompt / instruction_payload
 *     bodies (the backend allow-list filter prevents these fields
 *     from reaching the response, but the frontend also doesn't read
 *     any field that could carry them).
 *   - NEVER calls the rollback POST endpoint — this is a GET-only
 *     surface.
 *   - On 401: shows "Session expired or unauthenticated."
 *   - On 403: shows "You do not have permission to view rollback
 *     history."
 *   - On any other error: shows "Rollback history unavailable."
 *
 * Testids:
 *   - rollback-history-modal-root
 *   - rollback-history-loading
 *   - rollback-history-empty
 *   - rollback-history-error
 *   - rollback-history-row-{id}
 *   - rollback-history-agent-filter
 */
import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { api } from "@/services/api";
import type { PromptVersionRollbackHistoryItem } from "@/types/domain";

export interface RollbackHistoryModalProps {
  open: boolean;
  onOpenChange: (next: boolean) => void;
}

type LoadState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "loaded"; items: PromptVersionRollbackHistoryItem[]; count: number }
  | { kind: "error"; message: string; status?: number };

function fmtTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function classifyError(err: unknown): { message: string; status?: number } {
  if (err instanceof Error) {
    const msg = err.message;
    if (msg.includes("401")) {
      return {
        message: "Session expired or unauthenticated.",
        status: 401,
      };
    }
    if (msg.includes("403")) {
      return {
        message: "You do not have permission to view rollback history.",
        status: 403,
      };
    }
    return { message: "Rollback history unavailable." };
  }
  return { message: "Rollback history unavailable." };
}

export function RollbackHistoryModal({
  open,
  onOpenChange,
}: RollbackHistoryModalProps) {
  const [state, setState] = useState<LoadState>({ kind: "idle" });
  const [agentFilter, setAgentFilter] = useState<string>("");

  const load = async (agent: string) => {
    setState({ kind: "loading" });
    try {
      const res = await api.getPromptVersionRollbackHistory(
        agent ? { agent, limit: 50 } : { limit: 50 },
      );
      setState({
        kind: "loaded",
        items: res.items,
        count: res.count,
      });
    } catch (err) {
      const { message, status } = classifyError(err);
      setState({ kind: "error", message, status });
    }
  };

  useEffect(() => {
    if (open) {
      load(agentFilter);
    } else {
      setState({ kind: "idle" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const onAgentChange = (next: string) => {
    setAgentFilter(next);
    void load(next);
  };

  // Unique agents from the loaded items — keeps the filter dropdown
  // limited to agents that actually have rollback history.
  const agentsInHistory =
    state.kind === "loaded"
      ? Array.from(new Set(state.items.map((row) => row.agent))).sort()
      : [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="rollback-history-modal-root"
        className="max-w-3xl"
      >
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">
            Rollback history
          </DialogTitle>
          <DialogDescription>
            Read-only audit trail of every prompt-version rollback. Shows
            UI-triggered rollbacks (Phase 14F) and service-triggered rollbacks
            (legacy Phase 3D path). Prompt bodies are intentionally not
            rendered here — open the Governance page to inspect the prompt
            content if needed.
          </DialogDescription>
        </DialogHeader>

        {/* Agent filter — only enabled once we have items to filter. */}
        <div className="mb-3 flex items-center gap-2">
          <label className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Agent
          </label>
          <select
            data-testid="rollback-history-agent-filter"
            value={agentFilter}
            onChange={(event) => onAgentChange(event.target.value)}
            disabled={state.kind === "loading"}
            className="rounded-lg border border-border bg-background px-3 py-1.5 text-sm focus:border-ring focus:outline-none focus:ring-2 focus:ring-ring/20"
          >
            <option value="">All agents</option>
            {agentsInHistory.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void load(agentFilter)}
            disabled={state.kind === "loading"}
          >
            Refresh
          </Button>
        </div>

        {state.kind === "loading" && (
          <div
            data-testid="rollback-history-loading"
            className="rounded-lg bg-muted/40 p-4 text-sm text-muted-foreground"
          >
            Loading rollback history…
          </div>
        )}

        {state.kind === "error" && (
          <div
            data-testid="rollback-history-error"
            data-error-status={state.status ?? ""}
            className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
          >
            {state.message}
          </div>
        )}

        {state.kind === "loaded" && state.items.length === 0 && (
          <div
            data-testid="rollback-history-empty"
            className="rounded-lg bg-muted/40 p-4 text-sm text-muted-foreground"
          >
            No rollback history yet.
          </div>
        )}

        {state.kind === "loaded" && state.items.length > 0 && (
          <div className="max-h-[55vh] overflow-y-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-muted/40 text-[11px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="text-left font-medium px-3 py-2">Time</th>
                  <th className="text-left font-medium px-3 py-2">Agent</th>
                  <th className="text-left font-medium px-3 py-2">Change</th>
                  <th className="text-left font-medium px-3 py-2">Reason</th>
                  <th className="text-left font-medium px-3 py-2">Actor</th>
                  <th className="text-left font-medium px-3 py-2">Source</th>
                </tr>
              </thead>
              <tbody>
                {state.items.map((row) => (
                  <tr
                    key={row.id}
                    data-testid={`rollback-history-row-${row.id}`}
                    className="border-t border-border/40 align-top"
                  >
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {fmtTime(row.createdAt)}
                    </td>
                    <td className="px-3 py-2 font-medium">
                      {row.agent || "—"}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {row.previousVersionLabel || "?"} →{" "}
                      <span className="font-medium">
                        {row.targetVersionLabel || "?"}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground max-w-[260px] truncate">
                      {row.reason || "—"}
                    </td>
                    <td className="px-3 py-2 text-xs">{row.actor || "—"}</td>
                    <td className="px-3 py-2 text-[11px] uppercase tracking-wider text-muted-foreground">
                      {row.source === "settings_ui"
                        ? "UI"
                        : row.source === "service"
                          ? "Service"
                          : row.source}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {state.kind === "loaded" && (
          <div className="mt-3 text-[11px] text-muted-foreground">
            Showing {state.items.length} of {state.count} rollback{state.count === 1 ? "" : "s"}.
            History is read-only — to actually roll back, use{" "}
            <strong>Choose rollback target…</strong>.
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default RollbackHistoryModal;
