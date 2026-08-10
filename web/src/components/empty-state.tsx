import type { LucideIcon } from "lucide-react";
import * as React from "react";

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      <Icon className="size-10 text-muted-foreground/60" strokeWidth={1.5} />
      <div className="flex flex-col gap-1">
        <h3 className="text-[17px] font-semibold">{title}</h3>
        <p className="mx-auto max-w-sm text-[13px] text-muted-foreground">{description}</p>
      </div>
      {action}
    </div>
  );
}
