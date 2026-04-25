import { NavLink, useLocation } from "react-router-dom";
import {
  LayoutDashboard, Users, UserCircle2, PhoneCall, Workflow, ClipboardCheck,
  CreditCard, Truck, ShieldAlert, Bot, Sparkles, Gavel, Trophy,
  GraduationCap, FileBadge2, BarChart3, Settings2, Leaf, ChevronLeft,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useState } from "react";

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
  { to: "/rewards", label: "Reward & Penalty", icon: Trophy, group: "Governance" },
  { to: "/learning", label: "Call Learning Studio", icon: GraduationCap, group: "Governance" },
  { to: "/claims", label: "Claim Vault", icon: FileBadge2, group: "Governance" },
  { to: "/analytics", label: "Analytics", icon: BarChart3, group: "Insights" },
  { to: "/settings", label: "Settings & Control", icon: Settings2, group: "System" },
];

interface SidebarProps {
  open: boolean;
  onClose: () => void;
}

export function Sidebar({ open, onClose }: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
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
            "linear-gradient(180deg, hsl(158 42% 9%) 0%, hsl(158 38% 11%) 60%, hsl(168 38% 13%) 100%)",
        }}
      >
        {/* Brand */}
        <div className="flex items-center gap-3 px-5 h-16 border-b border-sidebar-border/70">
          <div className="relative">
            <div className="h-9 w-9 rounded-xl bg-gradient-gold grid place-items-center shadow-glow">
              <Leaf className="h-5 w-5 text-sidebar-primary-foreground" strokeWidth={2.4} />
            </div>
          </div>
          {!collapsed && (
            <div className="leading-tight">
              <div className="font-display text-[15px] font-semibold tracking-tight text-sidebar-foreground">
                Nirogidhara
              </div>
              <div className="text-[10px] uppercase tracking-[0.18em] text-sidebar-foreground/60">
                AI Command Center
              </div>
            </div>
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto scrollbar-thin py-4 px-2">
          {groups.map((g) => (
            <div key={g} className="mb-4">
              {!collapsed && (
                <div className="px-3 pb-1.5 text-[10px] font-medium uppercase tracking-[0.18em] text-sidebar-foreground/45">
                  {g}
                </div>
              )}
              <ul className="space-y-0.5">
                {NAV.filter((n) => n.group === g).map((item) => {
                  const active = location.pathname === item.to;
                  const Icon = item.icon;
                  return (
                    <li key={item.to}>
                      <NavLink
                        to={item.to}
                        onClick={onClose}
                        className={cn(
                          "group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-all duration-200",
                          active
                            ? "bg-sidebar-accent text-sidebar-foreground shadow-soft"
                            : "text-sidebar-foreground/70 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground",
                        )}
                      >
                        {active && (
                          <span className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-r bg-gradient-gold" />
                        )}
                        <Icon className={cn("h-[18px] w-[18px] shrink-0", active && "text-sidebar-primary")} />
                        {!collapsed && <span className="truncate">{item.label}</span>}
                      </NavLink>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>

        {/* Collapse */}
        <div className="hidden lg:flex items-center justify-end p-2 border-t border-sidebar-border/70">
          <button
            onClick={() => setCollapsed((c) => !c)}
            className="p-1.5 rounded-md hover:bg-sidebar-accent text-sidebar-foreground/60 hover:text-sidebar-foreground transition"
            aria-label="Collapse sidebar"
          >
            <ChevronLeft className={cn("h-4 w-4 transition-transform", collapsed && "rotate-180")} />
          </button>
        </div>
      </aside>
    </>
  );
}