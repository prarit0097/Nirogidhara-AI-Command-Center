import { cn } from "@/lib/utils";
import { ArrowDownRight, ArrowUpRight, LucideIcon } from "lucide-react";
import { ReactNode } from "react";

export function MetricCard({
  icon: Icon,
  label,
  value,
  delta,
  sublabel,
  tone = "primary",
  spark,
  className,
}: {
  icon: LucideIcon;
  label: string;
  value: ReactNode;
  delta?: number;
  sublabel?: string;
  tone?: "primary" | "accent" | "success" | "warning" | "danger" | "info";
  spark?: ReactNode;
  className?: string;
}) {
  const toneMap: Record<string, string> = {
    primary: "from-primary/10 to-primary/0 text-primary",
    accent: "from-accent/15 to-accent/0 text-accent",
    success: "from-success/15 to-success/0 text-success",
    warning: "from-warning/15 to-warning/0 text-warning",
    danger: "from-destructive/15 to-destructive/0 text-destructive",
    info: "from-info/15 to-info/0 text-info",
  };
  const positive = (delta ?? 0) >= 0;
  return (
    <div className={cn("surface-card p-5 group hover:shadow-elevated transition-all duration-300 animate-rise", className)}>
      <div className="flex items-start justify-between">
        <div className={cn("h-10 w-10 rounded-xl grid place-items-center bg-gradient-to-br border border-current/10", toneMap[tone])}>
          <Icon className="h-[18px] w-[18px]" />
        </div>
        {typeof delta === "number" && (
          <span
            className={cn(
              "inline-flex items-center gap-0.5 text-[11px] font-semibold rounded-full px-1.5 py-0.5",
              positive ? "text-success bg-success/10" : "text-destructive bg-destructive/10",
            )}
          >
            {positive ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
            {Math.abs(delta).toFixed(1)}%
          </span>
        )}
      </div>
      <div className="mt-4">
        <div className="text-[12px] uppercase tracking-wider text-muted-foreground font-medium">{label}</div>
        <div className="font-display text-3xl font-semibold mt-1 text-foreground">{value}</div>
        {sublabel && <div className="text-xs text-muted-foreground mt-1">{sublabel}</div>}
      </div>
      {spark && <div className="mt-3 -mx-1">{spark}</div>}
    </div>
  );
}