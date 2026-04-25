import { CheckCircle2, Circle, CircleDot } from "lucide-react";
import { cn } from "@/lib/utils";

interface WorkflowMapProps {
  title: string;
  description?: string;
  steps: string[];
  activeIndex?: number;
  compact?: boolean;
}

export function WorkflowMap({ title, description, steps, activeIndex = 0, compact = false }: WorkflowMapProps) {
  return (
    <section className="surface-card p-5 sm:p-6">
      <div className="mb-4">
        <h3 className="font-display text-lg font-semibold">{title}</h3>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      <div className="overflow-x-auto pb-1">
        <ol className={cn("flex min-w-max items-stretch", compact ? "gap-2" : "gap-3")}>
          {steps.map((step, index) => {
            const done = index < activeIndex;
            const active = index === activeIndex;
            const Icon = done ? CheckCircle2 : active ? CircleDot : Circle;

            return (
              <li key={step} className="flex items-center gap-2">
                <div
                  className={cn(
                    "min-h-[74px] w-[168px] rounded-xl border p-3 transition-colors",
                    done && "border-success/30 bg-success/10",
                    active && "border-accent/50 bg-accent-soft shadow-soft",
                    !done && !active && "border-border/70 bg-muted/30",
                  )}
                >
                  <Icon
                    className={cn(
                      "mb-2 h-4 w-4",
                      done && "text-success",
                      active && "text-accent",
                      !done && !active && "text-muted-foreground",
                    )}
                  />
                  <div className="text-xs font-medium leading-snug text-foreground">{step}</div>
                </div>
                {index < steps.length - 1 && <div className="h-px w-5 shrink-0 bg-border" />}
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}
