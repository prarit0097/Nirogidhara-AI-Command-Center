import { cn } from "@/lib/utils";
import { ReactNode } from "react";

type Tone = "success" | "warning" | "danger" | "info" | "neutral" | "accent";

const TONES: Record<Tone, string> = {
  success: "bg-success/10 text-success border-success/20",
  warning: "bg-warning/10 text-warning border-warning/20",
  danger: "bg-destructive/10 text-destructive border-destructive/20",
  info: "bg-info/10 text-info border-info/20",
  accent: "bg-accent-soft text-accent-foreground border-accent/30",
  neutral: "bg-muted text-muted-foreground border-border",
};

export function StatusPill({
  tone = "neutral",
  children,
  icon,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium",
        TONES[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}

export function toneForStatus(status: string): Tone {
  const s = status.toLowerCase();
  if (["delivered", "paid", "confirmed", "active", "approved", "convinced", "pass", "completed"].some((x) => s.includes(x))) return "success";
  if (["pending", "in transit", "queued", "in review", "callback", "interested", "live"].some((x) => s.includes(x))) return "info";
  if (["risk", "warning", "rescue", "hesitant", "partial", "weak"].some((x) => s.includes(x))) return "warning";
  if (["failed", "rto", "cancelled", "missed", "annoyed", "invalid", "critical", "danger", "high"].some((x) => s.includes(x))) return "danger";
  if (["new"].some((x) => s.includes(x))) return "accent";
  return "neutral";
}