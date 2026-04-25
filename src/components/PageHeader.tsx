import { ReactNode } from "react";

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-5 mb-7 lg:mb-9">
      <div className="max-w-3xl">
        {eyebrow && (
          <div className="inline-flex items-center gap-2 mb-3">
            <span className="h-1 w-6 rounded-full bg-gradient-gold" />
            <span className="text-[10.5px] uppercase tracking-[0.24em] text-accent font-semibold">
              {eyebrow}
            </span>
          </div>
        )}
        <h1 className="font-display text-[28px] leading-[1.1] sm:text-[36px] sm:leading-[1.08] font-semibold text-foreground text-balance">
          {title}
        </h1>
        {description && (
          <p className="mt-3 text-muted-foreground text-[14.5px] leading-relaxed text-pretty max-w-2xl">{description}</p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}