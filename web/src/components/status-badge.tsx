import { Badge } from "@/components/ui/badge";
import type { Decision, ToolStatus, UpstreamStatus } from "@/lib/types";

const TOOL: Record<ToolStatus, { label: string; variant: "neutral" | "success" | "warning" | "danger" | "info" }> = {
  approved: { label: "Approved", variant: "success" },
  pending: { label: "Pending", variant: "info" },
  quarantined: { label: "Quarantined", variant: "danger" },
  rejected: { label: "Rejected", variant: "neutral" },
};

export function ToolStatusBadge({ status }: { status: ToolStatus }) {
  const config = TOOL[status];
  return <Badge variant={config.variant}>{config.label}</Badge>;
}

const UPSTREAM: Record<UpstreamStatus, { label: string; variant: "neutral" | "success" | "warning" | "danger" }> = {
  connected: { label: "Connected", variant: "success" },
  pending: { label: "Connecting", variant: "warning" },
  degraded: { label: "Degraded", variant: "danger" },
  disabled: { label: "Disabled", variant: "neutral" },
};

export function UpstreamStatusBadge({ status }: { status: UpstreamStatus }) {
  const config = UPSTREAM[status];
  return (
    <Badge variant={config.variant}>
      <span className="size-1.5 rounded-full bg-current" />
      {config.label}
    </Badge>
  );
}

const DECISION: Record<Decision, { label: string; variant: "success" | "danger" | "warning" | "neutral" }> = {
  allowed: { label: "Allowed", variant: "success" },
  denied: { label: "Denied", variant: "danger" },
  quarantined: { label: "Quarantined", variant: "danger" },
  rate_limited: { label: "Rate limited", variant: "warning" },
  unknown_tool: { label: "Unknown tool", variant: "neutral" },
  upstream_error: { label: "Upstream error", variant: "warning" },
};

export function DecisionBadge({ decision }: { decision: Decision }) {
  const config = DECISION[decision];
  return <Badge variant={config.variant}>{config.label}</Badge>;
}
