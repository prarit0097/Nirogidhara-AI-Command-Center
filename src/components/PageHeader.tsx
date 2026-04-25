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
    <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4 mb-6 lg:mb-8">
      <div className="max-w-3xl">
        {eyebrow && (
          <div className="text-[11px] uppercase tracking-[0.22em] text-accent font-semibold mb-2">
            {eyebrow}
          </div>
        )}
        <h1 className="font-display text-3xl sm:text-4xl font-semibold text-foreground text-balance">
          {title}
        </h1>
        {description && (
          <p className="mt-2 text-muted-foreground text-[15px] leading-relaxed">{description}</p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}