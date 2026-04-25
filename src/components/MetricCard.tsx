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
  emphasis = false,
}: {
  icon: LucideIcon;
  label: string;
  value: ReactNode;
  delta?: number;
  sublabel?: string;
  tone?: "primary" | "accent" | "success" | "warning" | "danger" | "info";
  spark?: ReactNode;
  className?: string;
  emphasis?: boolean;
}) {
  const toneMap: Record<string, string> = {
    primary: "from-primary/12 to-primary/0 text-primary ring-primary/15",
    accent: "from-accent/18 to-accent/0 text-accent ring-accent/20",
    success: "from-success/18 to-success/0 text-success ring-success/20",
    warning: "from-warning/18 to-warning/0 text-warning ring-warning/20",
    danger: "from-destructive/18 to-destructive/0 text-destructive ring-destructive/20",
    info: "from-info/18 to-info/0 text-info ring-info/20",
  };
  const positive = (delta ?? 0) >= 0;
  return (
    <div
      className={cn(
        "surface-card relative overflow-hidden p-5 group hover-lift",
        emphasis && "gradient-border",
        className,
      )}
    >
      {/* corner glow */}
      <div
        aria-hidden
        className={cn(
          "pointer-events-none absolute -top-12 -right-12 h-32 w-32 rounded-full blur-2xl opacity-0 group-hover:opacity-60 transition-opacity duration-500",
          tone === "success" && "bg-success/30",
          tone === "warning" && "bg-warning/30",
          tone === "danger" && "bg-destructive/30",
          tone === "info" && "bg-info/30",
          tone === "accent" && "bg-accent/30",
          tone === "primary" && "bg-primary/30",
        )}
      />
      <div className="relative flex items-start justify-between">
        <div
          className={cn(
            "h-10 w-10 rounded-xl grid place-items-center bg-gradient-to-br ring-1 ring-inset",
            toneMap[tone],
          )}
        >
          <Icon className="h-[18px] w-[18px]" strokeWidth={2.2} />
        </div>
        {typeof delta === "number" && (
          <span
            className={cn(
              "inline-flex items-center gap-0.5 text-[11px] font-semibold rounded-full px-2 py-0.5 tabular-nums",
              positive
                ? "text-success bg-success/10 ring-1 ring-inset ring-success/15"
                : "text-destructive bg-destructive/10 ring-1 ring-inset ring-destructive/15",
            )}
          >
            {positive ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
            {Math.abs(delta).toFixed(1)}%
          </span>
        )}
      </div>
      <div className="relative mt-5">
        <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground font-semibold">{label}</div>
        <div className={cn("font-display font-semibold mt-1.5 text-foreground tracking-tight", emphasis ? "text-4xl" : "text-[28px] leading-tight")}>
          {value}
        </div>
        {sublabel && <div className="text-[12px] text-muted-foreground mt-1.5">{sublabel}</div>}
      </div>
      {spark && <div className="relative mt-3 -mx-1">{spark}</div>}
    </div>
  );
}