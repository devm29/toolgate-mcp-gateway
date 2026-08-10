import type { LucideIcon } from "lucide-react";

import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function KpiTile({
  label,
  value,
  hint,
  icon: Icon,
  tone = "default",
}: {
  label: string;
  value: string | number;
  hint?: string;
  icon: LucideIcon;
  tone?: "default" | "danger" | "success";
}) {
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between">
        <span className="text-[13px] text-muted-foreground">{label}</span>
        <Icon
          className={cn(
            "size-4",
            tone === "danger" ? "text-destructive" : tone === "success" ? "text-success-text" : "text-muted-foreground",
          )}
          strokeWidth={1.75}
        />
      </div>
      <div className="mt-2 text-[28px] font-semibold leading-none tabular tracking-tight">{value}</div>
      {hint ? <div className="mt-1.5 text-[12px] text-muted-foreground">{hint}</div> : null}
    </Card>
  );
}
