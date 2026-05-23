import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { api } from "@/services/api";
import type {
  AiSandboxModeAction,
  AiSandboxModeStatus,
  PromptVersion,
  SaasRuntimeLiveGateKillSwitch,
  SaasRuntimeLiveGateKillSwitchAction,
  WhatsAppProviderStatus,
} from "@/types/domain";
import {
  Boxes,
  KeyRound,
  MessageSquare,
  Power,
  RotateCcw,
  ShieldCheck,
  ScrollText,
  Beaker,
} from "lucide-react";
import { toast } from "sonner";
import KillSwitchModal from "@/components/KillSwitchModal";
import SandboxModeModal from "@/components/SandboxModeModal";
import RollbackSystemModal from "@/components/RollbackSystemModal";
import RollbackHistoryModal from "@/components/RollbackHistoryModal";
import { SafetyDiagnosticsPanel } from "@/components/settings/SafetyDiagnosticsPanel";

export default function Settings() {
  const [data, setData] = useState<any>(null);
  const [whatsappStatus, setWhatsappStatus] = useState<
    WhatsAppProviderStatus | null
  >(null);
  // Phase 14D — real backend-wired AI Kill Switch state.
  const [killSwitchState, setKillSwitchState] =
    useState<SaasRuntimeLiveGateKillSwitch | null>(null);
  const [killModal, setKillModal] = useState<
    SaasRuntimeLiveGateKillSwitchAction | null
  >(null);
  // Phase 14E — real backend-wired Sandbox Mode state.
  const [sandboxState, setSandboxState] =
    useState<AiSandboxModeStatus | null>(null);
  const [sandboxModal, setSandboxModal] =
    useState<AiSandboxModeAction | null>(null);
  // Phase 14F — real backend-wired Rollback System state.
  const [promptVersions, setPromptVersions] = useState<
    PromptVersion[] | null
  >(null);
  const [promptVersionsError, setPromptVersionsError] = useState(false);
  const [rollbackOpen, setRollbackOpen] = useState(false);
  // Phase 15A — Rollback History modal open state.
  const [rollbackHistoryOpen, setRollbackHistoryOpen] = useState(false);

  const refreshKillSwitch = async () => {
    try {
      const next = await api.getSaasRuntimeLiveGateKillSwitch();
      setKillSwitchState(next);
    } catch (err) {
      // Surface failure as a toast but do not crash the page.
      const message =
        err instanceof Error ? err.message : "Failed to load kill switch state";
      toast.error(`AI Kill Switch: ${message}`);
    }
  };

  const refreshSandbox = async () => {
    try {
      const next = await api.getAiSandboxModeStatus();
      setSandboxState(next);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to load sandbox state";
      toast.error(`Sandbox Mode: ${message}`);
    }
  };

  const refreshPromptVersions = async () => {
    try {
      const next = await api.listPromptVersions();
      setPromptVersions(next);
      setPromptVersionsError(false);
    } catch (err) {
      setPromptVersionsError(true);
      const message =
        err instanceof Error
          ? err.message
          : "Failed to load prompt versions";
      toast.error(`Rollback System: ${message}`);
    }
  };

  useEffect(() => {
    api.getSettingsMock().then(setData);
    api.getWhatsAppProviderStatus().then(setWhatsappStatus);
    refreshKillSwitch();
    refreshSandbox();
    refreshPromptVersions();
  }, []);
  if (!data) return <div className="h-96 grid place-items-center text-muted-foreground">Loading…</div>;

  const aiPaused = Boolean(
    killSwitchState?.aiExecutionBlocked ?? killSwitchState?.enabled ?? false,
  );
  const statusLabel = aiPaused ? "AI Paused" : "AI Running";
  const statusTone = aiPaused ? "warning" : "success";
  const statusDescription = killSwitchState
    ? aiPaused
      ? "Daily agent sweeps and Phase 7+/12A execute gates are blocked. Use Resume only after the incident is resolved."
      : "Daily agent sweeps are allowed. Activate emergency stop to pause all automated AI agents."
    : "Loading current state from backend…";

  return (
    <>
      <PageHeader eyebrow="System" title="Settings & Control Center"
        description="Roles, governance, AI safety controls, integrations and audit ledger — everything that keeps the system safe."
      />

      <div className="grid lg:grid-cols-3 gap-4 mb-6">
        {/* Phase 14D — AI Kill Switch card is wired to the real
            RuntimeKillSwitch row through
            POST /api/v1/saas/runtime-live-gate/kill-switch/. Activate
            and Resume both require a typed confirmation phrase + reason
            captured into the AuditEvent payload. */}
        <div className="surface-card p-5 border-l-4 border-l-destructive">
          <div className="flex items-center justify-between mb-2">
            <Power
              className={`h-5 w-5 ${aiPaused ? "text-warning" : "text-destructive"}`}
            />
            <StatusPill tone={statusTone}>{statusLabel}</StatusPill>
          </div>
          <div className="font-display text-lg font-semibold">AI Kill Switch</div>
          <div className="text-xs text-muted-foreground">{statusDescription}</div>
          {killSwitchState?.reason && (
            <div className="mt-3 rounded-lg bg-muted/40 p-2 text-[11px] text-muted-foreground">
              <span className="font-medium text-foreground">Last reason:</span>{" "}
              {killSwitchState.reason}
              {killSwitchState.updatedBy && (
                <span> · by {killSwitchState.updatedBy}</span>
              )}
            </div>
          )}
          <div className="mt-3 flex gap-2">
            <Button
              data-testid="settings-kill-switch-activate"
              variant="destructive"
              size="sm"
              disabled={aiPaused || !killSwitchState}
              onClick={() => setKillModal("activate_emergency_stop")}
            >
              Activate emergency stop
            </Button>
            <Button
              data-testid="settings-kill-switch-resume"
              variant="outline"
              size="sm"
              disabled={!aiPaused || !killSwitchState}
              onClick={() => setKillModal("resume_ai_operations")}
            >
              Resume AI operations
            </Button>
          </div>
        </div>
        {/* Phase 14E — Sandbox Mode card is wired to the real
            SandboxState singleton through
            POST /api/ai/sandbox/status/. Enable and Disable both
            require a typed confirmation phrase + reason captured into
            the AuditEvent payload. Disable additionally routes
            through the Phase 4C approval matrix
            (`ai.sandbox.disable` / director_override) — preserved. */}
        <div className="surface-card p-5 border-l-4 border-l-info">
          <div className="flex items-center justify-between mb-2">
            <Beaker
              className={`h-5 w-5 ${sandboxState?.isEnabled ? "text-warning" : "text-info"}`}
            />
            <StatusPill tone={sandboxState?.isEnabled ? "warning" : "info"}>
              {sandboxState
                ? sandboxState.isEnabled
                  ? "Sandbox ON"
                  : "Sandbox OFF"
                : "Loading…"}
            </StatusPill>
          </div>
          <div className="font-display text-lg font-semibold">Sandbox Mode</div>
          <div className="text-xs text-muted-foreground">
            {sandboxState
              ? sandboxState.isEnabled
                ? "AgentRuns are stamped sandbox_mode=true; CEO success path skips CeoBriefing refresh — no visible business-state mutation from AI."
                : "AI agents run normally with live business-state behavior. Enable sandbox to shadow-test new prompts/playbooks first."
              : "Loading current state from backend…"}
          </div>
          {sandboxState?.reason && (
            <div className="mt-3 rounded-lg bg-muted/40 p-2 text-[11px] text-muted-foreground">
              <span className="font-medium text-foreground">Last reason:</span>{" "}
              {sandboxState.reason}
              {sandboxState.updatedBy && (
                <span> · by {sandboxState.updatedBy}</span>
              )}
            </div>
          )}
          {/* Phase 14E-Hotfix-1 — render ONLY the valid state-transition
              action. While Sandbox is OFF, only Enable is shown; while
              Sandbox is ON, only Disable is shown. Loading state shows a
              neutral placeholder so the operator cannot blindly submit
              an action before backend state has loaded. */}
          <div className="mt-3 flex gap-2">
            {sandboxState === null ? (
              <span
                data-testid="settings-sandbox-loading"
                className="text-[11px] text-muted-foreground"
              >
                Loading state…
              </span>
            ) : sandboxState.isEnabled ? (
              <Button
                data-testid="settings-sandbox-disable"
                variant="destructive"
                size="sm"
                onClick={() => setSandboxModal("disable_sandbox_mode")}
              >
                Disable sandbox
              </Button>
            ) : (
              <Button
                data-testid="settings-sandbox-enable"
                variant="default"
                size="sm"
                onClick={() => setSandboxModal("enable_sandbox_mode")}
              >
                Enable sandbox
              </Button>
            )}
          </div>
        </div>
        {/* Phase 14F — Rollback System card wired to the real
            PromptVersion rollback path
            (POST /api/ai/prompt-versions/rollback-from-ui/).
            Modal requires agent + target-version selectors + reason
            + typed phrase "ROLLBACK PROMPT VERSION". The legacy mock
            toast Rollback button is removed. */}
        <div className="surface-card p-5 border-l-4 border-l-warning">
          <div className="flex items-center justify-between mb-2">
            <RotateCcw className="h-5 w-5 text-warning" />
            <StatusPill
              tone={
                promptVersionsError
                  ? "warning"
                  : promptVersions === null
                    ? "info"
                    : (promptVersions ?? []).some((v) => !v.isActive)
                      ? "info"
                      : "neutral"
              }
            >
              {promptVersionsError
                ? "Rollback state unavailable"
                : promptVersions === null
                  ? "Loading rollback state…"
                  : (promptVersions ?? []).some((v) => !v.isActive)
                    ? "Rollback ready"
                    : "No rollback candidates"}
            </StatusPill>
          </div>
          <div className="font-display text-lg font-semibold">Rollback System</div>
          <div className="text-xs text-muted-foreground">
            Revert an AI agent to a previous prompt/playbook version. Requires
            agent + target version selection, a 10+ char reason, and the typed
            phrase <code className="font-mono">ROLLBACK PROMPT VERSION</code>.
            Does not resume AI, toggle sandbox, send messages, or call
            customers.
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              data-testid="settings-rollback-open"
              variant="outline"
              size="sm"
              disabled={
                promptVersions === null ||
                promptVersionsError ||
                !(promptVersions ?? []).some((v) => !v.isActive)
              }
              onClick={() => setRollbackOpen(true)}
            >
              Choose rollback target…
            </Button>
            {/* Phase 15A — read-only history surface. Always available
                regardless of whether candidates exist (an operator may
                want to review past rollbacks even when nothing is
                currently eligible). */}
            <Button
              data-testid="settings-rollback-history-open"
              variant="ghost"
              size="sm"
              onClick={() => setRollbackHistoryOpen(true)}
            >
              View rollback history
            </Button>
          </div>
        </div>
      </div>
      {/* Phase 14D — single shared KillSwitchModal handles both
          activate and resume from the Settings card. The Topbar uses
          its own instance for emergency-stop only. */}
      {killModal && (
        <KillSwitchModal
          open={killModal !== null}
          onOpenChange={(next) => !next && setKillModal(null)}
          action={killModal}
          expectedPhrase={
            killModal === "activate_emergency_stop"
              ? killSwitchState?.confirmationPhrases?.activateEmergencyStop
              : killSwitchState?.confirmationPhrases?.resumeAiOperations
          }
          onSuccess={(next) => setKillSwitchState(next)}
        />
      )}
      {/* Phase 14E — Sandbox Mode modal. Same UX contract as
          KillSwitchModal: typed phrase + reason; backend re-validates;
          on success the sandbox card refreshes with the fresh state. */}
      {sandboxModal && (
        <SandboxModeModal
          open={sandboxModal !== null}
          onOpenChange={(next) => !next && setSandboxModal(null)}
          action={sandboxModal}
          expectedPhrase={
            sandboxModal === "enable_sandbox_mode"
              ? sandboxState?.confirmationPhrases?.enableSandboxMode
              : sandboxState?.confirmationPhrases?.disableSandboxMode
          }
          onSuccess={(next) => setSandboxState(next)}
        />
      )}
      {/* Phase 14F — Rollback System modal. Wraps the shared
          SafetyConfirmationModal with agent + target-version
          selectors above the reason/phrase block. Mounts only when
          opened so the agent + target lists are recomputed off the
          freshest promptVersions snapshot. */}
      {rollbackOpen && promptVersions !== null && (
        <RollbackSystemModal
          open={rollbackOpen}
          onOpenChange={(next) => setRollbackOpen(next)}
          versions={promptVersions}
          onSuccess={() => {
            // Refresh the list so the no-longer-eligible target +
            // the new active version are reflected in the next open.
            refreshPromptVersions();
          }}
        />
      )}
      {/* Phase 15A — read-only Rollback History modal. Lazy-mounted
          so the list endpoint is only hit when the operator opens
          the surface. */}
      {rollbackHistoryOpen && (
        <RollbackHistoryModal
          open={rollbackHistoryOpen}
          onOpenChange={(next) => setRollbackHistoryOpen(next)}
        />
      )}

      {/* Phase 15I — Safety Diagnostics mini panel. Read-only;
          consumes the shared SafetyStateProvider (Phase 15F) so no
          new fetches are issued. Sits between the three safety
          control cards above and the AI Action Approval Matrix
          below. */}
      <SafetyDiagnosticsPanel />

      <div className="surface-card overflow-hidden mb-6">
        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
          <h3 className="font-display text-lg font-semibold flex items-center gap-2"><ShieldCheck className="h-5 w-5 text-primary" />AI Action Approval Matrix</h3>
          <StatusPill tone="info">v2.1</StatusPill>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[600px]">
            <thead className="bg-muted/30 text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left font-medium px-6 py-3">Action</th>
                <th className="text-left font-medium py-3">Approval</th>
              </tr>
            </thead>
            <tbody>
              {/* Phase 14C — read backend's {action, approval} shape (not the
                  legacy mock {action, policy, approver}). Defensive
                  short-circuit on empty/missing approval so a future field
                  rename never crashes the entire React tree again. */}
              {data.approvalMatrix.map((a: { action: string; approval?: string }) => (
                <tr key={a.action} className="border-t border-border/60 hover:bg-muted/20">
                  <td className="px-6 py-3 font-medium">{a.action}</td>
                  <td className="py-3">
                    <StatusPill
                      tone={
                        !a.approval
                          ? "info"
                          : a.approval === "Auto"
                            ? "success"
                            : /hard|handoff|emergency|director|critical/i.test(a.approval)
                              ? "danger"
                              : /approval|review|manager/i.test(a.approval)
                                ? "warning"
                                : "info"
                      }
                    >
                      {a.approval || "—"}
                    </StatusPill>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="surface-card p-6 mb-6">
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-3">
            <MessageSquare className="h-5 w-5 text-primary" />
            <div>
              <h3 className="font-display text-lg font-semibold">
                WhatsApp Business (WABA)
              </h3>
              <p className="text-xs text-muted-foreground">
                Phase 5A · Meta Cloud is the production target. Mock provider
                runs in local dev so no live messages go out without consent
                + approved template + Claim Vault.
              </p>
            </div>
          </div>
          <Link to="/whatsapp-templates">
            <Button size="sm" variant="outline">
              View templates
            </Button>
          </Link>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <WabaStatField
            label="Provider"
            value={whatsappStatus?.provider ?? "—"}
            tone={
              whatsappStatus?.provider === "meta_cloud"
                ? "success"
                : whatsappStatus?.provider === "mock"
                  ? "info"
                  : "warning"
            }
          />
          <WabaStatField
            label="Health"
            value={
              whatsappStatus
                ? whatsappStatus.healthy
                  ? "healthy"
                  : "unhealthy"
                : "—"
            }
            tone={whatsappStatus?.healthy ? "success" : "warning"}
          />
          <WabaStatField
            label="Phone number"
            value={whatsappStatus?.connection?.phoneNumber || "not set"}
            tone={
              whatsappStatus?.connection?.phoneNumber ? "neutral" : "warning"
            }
          />
          <WabaStatField
            label="Phone number id"
            value={whatsappStatus?.connection?.phoneNumberId || "not set"}
            tone={
              whatsappStatus?.connection?.phoneNumberId
                ? "neutral"
                : "warning"
            }
          />
          <WabaStatField
            label="Access token"
            value={whatsappStatus?.accessTokenSet ? "configured" : "missing"}
            tone={whatsappStatus?.accessTokenSet ? "success" : "warning"}
          />
          <WabaStatField
            label="Verify token"
            value={whatsappStatus?.verifyTokenSet ? "configured" : "missing"}
            tone={whatsappStatus?.verifyTokenSet ? "success" : "warning"}
          />
          <WabaStatField
            label="App secret"
            value={whatsappStatus?.appSecretSet ? "configured" : "missing"}
            tone={whatsappStatus?.appSecretSet ? "success" : "warning"}
          />
          <WabaStatField
            label="API version"
            value={whatsappStatus?.apiVersion ?? "—"}
            tone="neutral"
          />
        </div>

        {whatsappStatus?.devProviderEnabled && (
          <div className="mt-3 text-xs text-warning">
            Dev-only Baileys provider toggle is ENABLED. Production must keep
            <code> WHATSAPP_DEV_PROVIDER_ENABLED=false</code>.
          </div>
        )}
      </div>

      <div className="grid lg:grid-cols-2 gap-6 mb-6">
        <div className="surface-card p-6">
          <h3 className="font-display text-lg font-semibold mb-4 flex items-center gap-2"><Boxes className="h-5 w-5 text-primary" />Integrations</h3>
          <div className="space-y-2">
            {data.integrations.map((i: any) => (
              <div key={i.name} className="flex items-center justify-between rounded-xl bg-muted/40 p-3">
                <div>
                  <div className="font-medium">{i.name}</div>
                  <div className="text-xs text-muted-foreground">{i.purpose}</div>
                </div>
                <div className="flex items-center gap-2">
                  <StatusPill tone={i.status === "Planned" ? "info" : "neutral"}>{i.status}</StatusPill>
                  <Button size="sm" variant="outline" onClick={() => toast.info(`Connect ${i.name} (mock)`)}>Connect</Button>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="surface-card p-6">
          <h3 className="font-display text-lg font-semibold mb-4 flex items-center gap-2"><KeyRound className="h-5 w-5 text-primary" />Roles & permissions</h3>
          <div className="space-y-2">
            {[
              { role: "Director", who: "Prarit Sidana", scope: "All" },
              { role: "Operations Manager", who: "—", scope: "Orders, Delivery, RTO" },
              { role: "Calling TL", who: "—", scope: "Calling, Confirmation" },
              { role: "Compliance Officer", who: "—", scope: "Claim Vault, CAIO" },
              { role: "Finance", who: "—", scope: "Payments, Net Profit" },
            ].map((r) => (
              <div key={r.role} className="flex items-center justify-between rounded-xl bg-muted/40 p-3">
                <div>
                  <div className="font-medium">{r.role}</div>
                  <div className="text-xs text-muted-foreground">{r.who}</div>
                </div>
                <StatusPill tone="info">{r.scope}</StatusPill>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="surface-card p-6">
        <h3 className="font-display text-lg font-semibold mb-3 flex items-center gap-2"><ScrollText className="h-5 w-5 text-primary" />Master Event Ledger</h3>
        <p className="text-sm text-muted-foreground mb-3">Immutable record of every AI decision, business event and approval.</p>
        <div className="font-mono text-xs bg-foreground text-background p-4 rounded-xl space-y-1 max-h-56 overflow-auto scrollbar-thin">
          <div>10:42:18  CEO_AI  approve  rec=rec-3  user=auto</div>
          <div>10:41:55  CALLING_AI  order_punched  order=NRG-20431</div>
          <div>10:41:02  COMPLIANCE  block  claim="permanent solution"</div>
          <div>10:40:11  RTO_AGENT  rescue_call  order=NRG-20418  result=convinced</div>
          <div>10:39:47  RAZORPAY  payment_received  amount=499  order=NRG-20431</div>
          <div>10:38:22  CAIO  flag  agent=Sales_Growth  severity=High</div>
        </div>
      </div>
    </>
  );
}

function ControlCard({ icon: Icon, title, desc, tone, children }: any) {
  const ring: any = { danger: "border-l-destructive", info: "border-l-info", warning: "border-l-warning" };
  return (
    <div className={`surface-card p-5 border-l-4 ${ring[tone]}`}>
      <div className="flex items-center justify-between mb-2">
        <Icon className={`h-5 w-5 text-${tone === "danger" ? "destructive" : tone}`} />
        {children}
      </div>
      <div className="font-display text-lg font-semibold">{title}</div>
      <div className="text-xs text-muted-foreground">{desc}</div>
    </div>
  );
}

interface WabaStatFieldProps {
  label: string;
  value: string;
  tone: "success" | "warning" | "info" | "neutral";
}

function WabaStatField({ label, value, tone }: WabaStatFieldProps) {
  return (
    <div className="rounded-xl bg-muted/40 px-3 py-3">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-1">
        {label}
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium truncate">{value}</span>
        <StatusPill tone={tone}>{tone}</StatusPill>
      </div>
    </div>
  );
}