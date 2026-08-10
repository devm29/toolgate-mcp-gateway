import * as React from "react";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 pb-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-[28px] font-semibold leading-tight tracking-tight">{title}</h1>
        {description ? <p className="text-[13px] text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}
