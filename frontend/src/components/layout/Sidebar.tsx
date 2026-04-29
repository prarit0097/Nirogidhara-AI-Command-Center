import { NavLink, useLocation } from "react-router-dom";
import {
  LayoutDashboard, Users, UserCircle2, PhoneCall, Workflow, ClipboardCheck,
  CreditCard, Truck, ShieldAlert, Bot, Sparkles, Gavel, Trophy,
  GraduationCap, FileBadge2, BarChart3, Settings2, Leaf, ChevronLeft,
  AlarmClock, ShieldCheck, MessageSquare, Inbox,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", label: "Command Center", icon: LayoutDashboard, group: "Overview" },
  { to: "/leads", label: "Leads CRM", icon: Users, group: "Sales" },
  { to: "/customers", label: "Customer 360", icon: UserCircle2, group: "Sales" },
  { to: "/calling", label: "AI Calling Console", icon: PhoneCall, group: "Sales" },
  { to: "/orders", label: "Orders Pipeline", icon: Workflow, group: "Operations" },
  { to: "/confirmation", label: "Confirmation Queue", icon: ClipboardCheck, group: "Operations" },
  { to: "/payments", label: "Payments", icon: CreditCard, group: "Operations" },
  { to: "/delivery", label: "Delhivery & Tracking", icon: Truck, group: "Operations" },
  { to: "/rto", label: "RTO Rescue Board", icon: ShieldAlert, group: "Operations" },
  { to: "/agents", label: "AI Agents Center", icon: Bot, group: "AI Layer" },
  { to: "/ceo-ai", label: "CEO AI Briefing", icon: Sparkles, group: "AI Layer" },
  { to: "/caio", label: "CAIO Audit Center", icon: Gavel, group: "AI Layer" },
  { to: "/ai-scheduler", label: "AI Scheduler & Cost", icon: AlarmClock, group: "AI Layer" },
  { to: "/ai-governance", label: "AI Governance", icon: ShieldCheck, group: "AI Layer" },
  { to: "/rewards", label: "Reward & Penalty", icon: Trophy, group: "Governance" },
  { to: "/learning", label: "Call Learning Studio", icon: GraduationCap, group: "Governance" },
  { to: "/claims", label: "Claim Vault", icon: FileBadge2, group: "Governance" },
  { to: "/analytics", label: "Analytics", icon: BarChart3, group: "Insights" },
  { to: "/whatsapp-inbox", label: "WhatsApp Inbox", icon: Inbox, group: "Messaging" },
  { to: "/whatsapp-templates", label: "WhatsApp Templates", icon: MessageSquare, group: "Messaging" },
  { to: "/settings", label: "Settings & Control", icon: Settings2, group: "System" },
];

interface SidebarProps {
  open: boolean;
  onClose: () => void;
  collapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
}

export function Sidebar({ open, onClose, collapsed, onCollapsedChange }: SidebarProps) {
  const location = useLocation();
  const groups = Array.from(new Set(NAV.map((n) => n.group)));

  return (
    <>
      {/* mobile overlay */}
      <div
        onClick={onClose}
        className={cn(
          "fixed inset-0 z-40 bg-foreground/40 backdrop-blur-sm lg:hidden transition-opacity",
          open ? "opacity-100" : "pointer-events-none opacity-0",
        )}
      />
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 bg-sidebar text-sidebar-foreground flex flex-col transition-all duration-300",
          "border-r border-sidebar-border",
          collapsed ? "w-[72px]" : "w-[260px]",
          "lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
        )}
        style={{
          background:
            "linear-gradient(180deg, hsl(162 46% 6%) 0%, hsl(162 40% 9%) 55%, hsl(168 38% 12%) 100%)",
        }}
      >
        {/* subtle ambient glow */}
        <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
          <div className="absolute -top-24 -left-16 h-56 w-56 rounded-full bg-accent/10 blur-3xl" />
          <div className="absolute bottom-12 -right-20 h-64 w-64 rounded-full bg-primary-glow/10 blur-3xl" />
        </div>
        {/* Brand */}
        <div className="relative flex items-center gap-3 px-5 h-[68px] border-b border-sidebar-border/60">
          <div className="relative">
            <div className="h-10 w-10 rounded-2xl bg-gradient-gold grid place-items-center shadow-glow ring-1 ring-accent/40">
              <Leaf className="h-[20px] w-[20px] text-sidebar-primary-foreground" strokeWidth={2.4} />
            </div>
            <span className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-success ring-2 ring-sidebar" />
          </div>
          {!collapsed && (
            <div className="leading-tight">
              <div className="font-display text-[16px] font-semibold tracking-tight text-sidebar-foreground">
                Nirogidhara
              </div>
              <div className="text-[10px] uppercase tracking-[0.22em] text-sidebar-foreground/55 font-medium">
                AI Command Center
              </div>
            </div>
          )}
        </div>

        {/* Nav */}
        <nav className="relative flex-1 overflow-y-auto scrollbar-thin py-4 px-2.5">
          {groups.map((g) => (
            <div key={g} className="mb-5">
              {!collapsed && (
                <div className="px-3 pb-2 text-[10px] font-semibold uppercase tracking-[0.22em] text-sidebar-foreground/40">
                  {g}
                </div>
              )}
              <ul className="space-y-[3px]">
                {NAV.filter((n) => n.group === g).map((item) => {
                  const active = location.pathname === item.to;
                  const Icon = item.icon;
                  return (
                    <li key={item.to}>
                      <NavLink
                        to={item.to}
                        onClick={onClose}
                        className={cn(
                          "group relative flex items-center gap-3 rounded-xl px-3 py-2 text-[13.5px] transition-all duration-200",
                          active
                            ? "bg-sidebar-accent text-sidebar-foreground shadow-soft font-medium"
                            : "text-sidebar-foreground/65 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground",
                        )}
                      >
                        {active && (
                          <>
                            <span className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-r bg-gradient-gold shadow-glow" />
                            <span className="absolute inset-0 rounded-xl bg-gradient-to-r from-accent/[0.08] to-transparent pointer-events-none" />
                          </>
                        )}
                        <Icon
                          className={cn(
                            "h-[17px] w-[17px] shrink-0 transition-colors",
                            active ? "text-sidebar-primary" : "text-sidebar-foreground/50 group-hover:text-sidebar-foreground/85",
                          )}
                          strokeWidth={active ? 2.2 : 1.8}
                        />
                        {!collapsed && <span className="truncate relative">{item.label}</span>}
                      </NavLink>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>

        {/* Footer — system + collapse */}
        <div className="relative border-t border-sidebar-border/60 p-3">
          {!collapsed && (
            <div className="mb-2 px-2 flex items-center gap-2 text-[11px] text-sidebar-foreground/55">
              <span className="h-1.5 w-1.5 rounded-full bg-success animate-pulse" />
              <span>All systems normal</span>
              <span className="ml-auto font-mono text-[10px] text-sidebar-foreground/40">v2.4</span>
            </div>
          )}
          <div className="hidden lg:flex items-center justify-end">
          <button
            onClick={() => onCollapsedChange(!collapsed)}
            className="p-1.5 rounded-md hover:bg-sidebar-accent text-sidebar-foreground/55 hover:text-sidebar-foreground transition"
            aria-label="Collapse sidebar"
          >
            <ChevronLeft className={cn("h-4 w-4 transition-transform", collapsed && "rotate-180")} />
          </button>
          </div>
        </div>
      </aside>
    </>
  );
}
