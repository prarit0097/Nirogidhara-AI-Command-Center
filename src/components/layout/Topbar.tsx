import { Bell, Command, Menu, Power, Search, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useState } from "react";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { toast } from "sonner";

export function Topbar({ onMenu }: { onMenu: () => void }) {
  const [killOpen, setKillOpen] = useState(false);

  return (
    <header className="sticky top-0 z-30 h-16 bg-background/80 backdrop-blur-xl border-b border-border/60">
      <div className="h-full px-4 lg:px-8 flex items-center gap-3">
        <button
          onClick={onMenu}
          className="lg:hidden p-2 -ml-2 rounded-lg hover:bg-muted text-foreground"
          aria-label="Open menu"
        >
          <Menu className="h-5 w-5" />
        </button>

        {/* Search */}
        <div className="hidden md:flex flex-1 max-w-xl">
          <div className="relative w-full">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <input
              placeholder="Search leads, orders, AWB, agents…"
              className="w-full h-10 pl-10 pr-16 rounded-xl bg-muted/60 border border-transparent hover:border-border focus:border-ring focus:bg-background outline-none text-sm transition"
            />
            <span className="hidden md:flex absolute right-3 top-1/2 -translate-y-1/2 items-center gap-1 text-[10px] text-muted-foreground font-mono px-1.5 py-0.5 rounded border border-border bg-background">
              <Command className="h-3 w-3" />K
            </span>
          </div>
        </div>

        <div className="flex-1 md:hidden" />

        {/* Live */}
        <div className="hidden sm:flex items-center gap-2 px-3 h-9 rounded-full bg-success/10 border border-success/20 text-success">
          <span className="live-dot" />
          <span className="text-xs font-medium">Live</span>
        </div>

        {/* CEO AI quick */}
        <Button
          variant="outline"
          size="sm"
          className="hidden md:inline-flex gap-1.5 border-accent/40 hover:bg-accent-soft hover:border-accent text-foreground"
          onClick={() => toast.success("CEO AI is preparing your briefing…")}
        >
          <Sparkles className="h-3.5 w-3.5 text-accent" />
          Ask CEO AI
        </Button>

        {/* Notifications */}
        <button className="relative h-9 w-9 grid place-items-center rounded-lg hover:bg-muted transition">
          <Bell className="h-4 w-4" />
          <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-destructive ring-2 ring-background" />
        </button>

        {/* Kill switch */}
        <Dialog open={killOpen} onOpenChange={setKillOpen}>
          <DialogTrigger asChild>
            <Button variant="destructive" size="sm" className="gap-1.5 shadow-soft">
              <Power className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">AI Kill Switch</span>
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle className="font-display text-2xl">Activate AI Kill Switch?</DialogTitle>
              <DialogDescription>
                This will <strong>immediately pause all AI agents</strong> across calling, ads,
                pricing, RTO rescue and creative generation. Human operators will continue. Use only
                during a critical incident or compliance issue.
              </DialogDescription>
            </DialogHeader>
            <div className="rounded-lg bg-destructive/10 border border-destructive/20 p-3 text-sm text-destructive">
              All in-flight AI calls will be safely handed off to human callers.
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setKillOpen(false)}>Cancel</Button>
              <Button
                variant="destructive"
                onClick={() => { setKillOpen(false); toast.error("AI Kill Switch ENGAGED — all AI agents paused (mock)."); }}
              >
                Engage Kill Switch
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* User */}
        <div className="flex items-center gap-2.5 pl-2 border-l border-border ml-1">
          <div className="h-9 w-9 rounded-full bg-gradient-hero text-primary-foreground grid place-items-center font-semibold text-sm shadow-soft">
            PS
          </div>
          <div className="hidden lg:block leading-tight">
            <div className="text-sm font-semibold">Prarit Sidana</div>
            <div className="text-[11px] text-muted-foreground">Director</div>
          </div>
        </div>
      </div>
    </header>
  );
}