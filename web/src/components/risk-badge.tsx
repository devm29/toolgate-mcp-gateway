import { ShieldAlert, ShieldCheck, ShieldQuestion } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { RiskLevel } from "@/lib/types";

const CONFIG: Record<RiskLevel, { label: string; variant: "neutral" | "success" | "warning" | "danger" | "info" }> = {
  none: { label: "Clean", variant: "success" },
  low: { label: "Low", variant: "info" },
  medium: { label: "Medium", variant: "warning" },
  high: { label: "High", variant: "danger" },
  critical: { label: "Critical", variant: "danger" },
};

export function RiskBadge({ level, score }: { level: RiskLevel; score?: number }) {
  const config = CONFIG[level];
  const Icon = level === "none" ? ShieldCheck : level === "low" ? ShieldQuestion : ShieldAlert;
  return (
    <Badge variant={config.variant}>
      <Icon className="size-3" strokeWidth={2} />
      {config.label}
      {score !== undefined && level !== "none" ? <span className="tabular">· {score}</span> : null}
    </Badge>
  );
}
