import { Bell, Command, LogOut, Menu, Power, Search, Sparkles, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { OrgBadge } from "./OrgBadge";
import { api } from "@/services/api";
import type {
  AiSandboxModeStatus,
  DirectorBriefingSidebarStatus,
  SaasRuntimeLiveGateKillSwitch,
} from "@/types/domain";
import KillSwitchModal from "@/components/KillSwitchModal";
import { computeTopbarSafetySummary } from "@/utils/topbarSafetySummary";
import { cn } from "@/lib/utils";

export function Topbar({ onMenu }: { onMenu: () => void }) {
  // Phase 14D — Topbar AI Kill Switch is wired to the real backend
  // RuntimeKillSwitch state. The Topbar button is emergency-stop ONLY:
  // it opens the activate_emergency_stop modal. Resume happens on
  // /settings (intentionally a heavier surface so resume isn't a
  // one-click anywhere on the chrome).
  const [killOpen, setKillOpen] = useState(false);
  const [state, setState] = useState<SaasRuntimeLiveGateKillSwitch | null>(
    null,
  );

  // Phase 15D — Topbar safety pill data. Reuses Phase 14E sandbox
  // + Phase 15B briefing endpoints; never mutates state.
  const [sandbox, setSandbox] = useState<AiSandboxModeStatus | null>(null);
  const [briefing, setBriefing] = useState<
    DirectorBriefingSidebarStatus | null
  >(null);
  const [killSwitchError, setKillSwitchError] = useState(false);
  const [sandboxError, setSandboxError] = useState(false);
  const [briefingError, setBriefingError] = useState(false);

  const refresh = async () => {
    try {
      const next = await api.getSaasRuntimeLiveGateKillSwitch();
      setState(next);
      setKillSwitchError(false);
    } catch (err) {
      // Phase 14D — surface load failure quietly; the Topbar should
      // not white-screen if the backend is briefly unreachable.
      // Settings page shows the canonical state on retry.
      console.error("[Topbar] kill-switch load failed:", err);
      setKillSwitchError(true);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  // Phase 15D — fire-and-forget reads for the safety pill. Errors
  // are recorded so the pill renders "unavailable" rather than
  // silently claiming a green posture.
  useEffect(() => {
    let cancelled = false;
    api
      .getAiSandboxModeStatus()
      .then((next) => !cancelled && setSandbox(next))
      .catch((err: unknown) => {
        if (cancelled) return;
        console.error("[Topbar] sandbox load failed:", err);
        setSandboxError(true);
      });
    api
      .getDirectorBriefingSidebarStatus()
      .then((next) => !cancelled && setBriefing(next))
      .catch((err: unknown) => {
        if (cancelled) return;
        console.error("[Topbar] briefing load failed:", err);
        setBriefingError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const aiPaused = Boolean(
    state?.aiExecutionBlocked ?? state?.enabled ?? false,
  );

  const safetyPill = computeTopbarSafetySummary({
    killSwitch: state,
    sandbox,
    briefing,
    killSwitchError,
    sandboxError,
    briefingError,
  });

  return (
    <header className="sticky top-0 z-30 h-[68px] bg-background/75 backdrop-blur-xl border-b border-border/60 supports-[backdrop-filter]:bg-background/60">
      {/* Phase 15E - min-w-0 lets flex children shrink correctly so
          the Topbar never overflows horizontally on common desktop
          widths. Without min-w-0 the chrome's intrinsic width (long
          Safety Pill label + multiple whitespace-nowrap chips + the
          search input) can exceed viewport and cause a body-level
          horizontal scrollbar. */}
      <div className="h-full px-4 lg:px-8 flex items-center gap-3 min-w-0">
        <button
          onClick={onMenu}
          className="lg:hidden p-2 -ml-2 rounded-lg hover:bg-muted text-foreground"
          aria-label="Open menu"
        >
          <Menu className="h-5 w-5" />
        </button>

        {/* Search — Phase 15E: min-w-0 + shrink so the input
            collapses when chrome to its right is busy, preventing
            a horizontal page scrollbar at narrower desktop widths. */}
        <div className="hidden md:flex flex-1 max-w-xl min-w-0 shrink">
          <div className="relative w-full">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground transition-colors" />
            <input
              placeholder="Search leads, orders, AWB, agents…"
              className="w-full h-10 pl-10 pr-16 rounded-xl bg-muted/50 border border-transparent hover:border-border/80 focus:border-ring/40 focus:bg-background focus:ring-4 focus:ring-ring/10 outline-none text-[13.5px] transition-all"
            />
            <span className="hidden md:flex absolute right-2.5 top-1/2 -translate-y-1/2 items-center gap-0.5 kbd">
              <Command className="h-3 w-3" />K
            </span>
          </div>
        </div>

        <div className="flex-1 md:hidden" />

        {/* Org badge (Phase 6A — read-only) */}
        <OrgBadge />

        {/* Phase 15D / 15E — Topbar Safety Compact Pill.
            Read-only summary of kill-switch + sandbox + briefing
            state. No click handler; never executes any action.
            Visible on md+ widths so the chrome stays uncluttered
            on mobile (full posture still surfaces on the Sidebar
            footer + Settings page).
            Phase 15E: responsive label - full text at xl+, compact
            text at md/lg so the Topbar fits at common desktop
            widths (1280-1366px) without forcing a page-level
            horizontal scrollbar. aria-label / title always carry
            the long-form tooltip regardless of which label is
            visually rendered. */}
        <span
          data-testid="topbar-safety-pill"
          data-safety-tone={safetyPill.tone}
          data-safety-status={safetyPill.dataStatus}
          role="status"
          aria-label={safetyPill.tooltip}
          title={safetyPill.tooltip}
          className={cn(
            "hidden md:inline-flex items-center gap-1.5 h-9 px-3 rounded-full border text-[11.5px] font-semibold whitespace-nowrap cursor-default select-none shrink-0",
            safetyPill.className,
          )}
        >
          <ShieldCheck className="h-3.5 w-3.5 shrink-0" />
          <span
            data-testid="topbar-safety-pill-label"
            className="hidden xl:inline"
          >
            {safetyPill.label}
          </span>
          <span
            data-testid="topbar-safety-pill-compact-label"
            className="xl:hidden"
          >
            {safetyPill.compactLabel}
          </span>
        </span>

        {/* Live */}
        <div className="hidden sm:flex items-center gap-2 px-3 h-9 rounded-full bg-success/8 border border-success/20 text-success">
          <span className="live-dot" />
          <span className="text-[11px] font-semibold uppercase tracking-wider">Live</span>
        </div>

        {/* CEO AI quick */}
        <Button
          variant="outline"
          size="sm"
          className="hidden md:inline-flex gap-1.5 h-9 border-accent/40 hover:bg-accent-soft hover:border-accent text-foreground rounded-lg shadow-sm"
          onClick={() => toast.success("CEO AI is preparing your briefing…")}
        >
          <Sparkles className="h-3.5 w-3.5 text-accent" />
          <span className="font-medium">Ask CEO AI</span>
        </Button>

        {/* Notifications */}
        <button className="relative h-9 w-9 grid place-items-center rounded-lg hover:bg-muted transition group" aria-label="Notifications">
          <Bell className="h-[17px] w-[17px] text-muted-foreground group-hover:text-foreground transition-colors" />
          <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-destructive ring-2 ring-background animate-pulse" />
        </button>

        {/* Phase 14D — AI Kill Switch (live, backend-wired).
            Button is emergency-stop only. While AI is already paused
            the button stays visible but shows the paused state — to
            resume, the operator goes to /settings (intentional friction
            so resume is never a one-click anywhere in the chrome). */}
        {aiPaused ? (
          <span
            data-testid="topbar-kill-switch-paused"
            title="AI is paused. Resume from Settings."
            className="hidden sm:inline-flex items-center gap-1.5 h-9 px-3 rounded-lg border border-warning/40 bg-warning/10 text-warning text-[12px] font-semibold"
          >
            <Power className="h-3.5 w-3.5" />
            AI Paused
          </span>
        ) : (
          <Button
            data-testid="topbar-kill-switch-button"
            variant="destructive"
            size="sm"
            className="gap-1.5 h-9 rounded-lg shadow-soft hover:shadow-elevated transition-shadow"
            onClick={() => setKillOpen(true)}
            disabled={!state}
            aria-label="Open AI Kill Switch confirmation"
          >
            <Power className="h-3.5 w-3.5" />
            <span className="hidden sm:inline font-medium">AI Kill Switch</span>
          </Button>
        )}
        <KillSwitchModal
          open={killOpen}
          onOpenChange={setKillOpen}
          action="activate_emergency_stop"
          expectedPhrase={
            state?.confirmationPhrases?.activateEmergencyStop
          }
          onSuccess={(next) => setState(next)}
        />

        {/* User */}
        <div className="flex items-center gap-2.5 pl-3 border-l border-border ml-1">
          <div className="relative">
            <div className="h-9 w-9 rounded-full bg-gradient-hero text-primary-foreground grid place-items-center font-semibold text-[12px] shadow-soft ring-2 ring-background">
              PS
            </div>
            <span className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-success ring-2 ring-background" />
          </div>
          <div className="hidden lg:block leading-tight">
            <div className="text-[13px] font-semibold">Prarit Sidana</div>
            <div className="text-[10.5px] text-muted-foreground uppercase tracking-wider">Director</div>
          </div>
          {/* Phase 13A — Logout action. Clears the JWT and dispatches
              the auth-cleared event, which trips RequireAuth and routes
              the user back to /login. */}
          <button
            type="button"
            aria-label="Sign out"
            title="Sign out"
            data-testid="topbar-logout-button"
            onClick={() => {
              if (typeof window !== "undefined") {
                window.localStorage.removeItem("nirogidhara.jwt");
                window.dispatchEvent(new Event("nirogidhara:auth-cleared"));
              }
            }}
            className="ml-1 p-2 rounded-md hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </header>
  );
}