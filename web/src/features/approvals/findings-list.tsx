import { AlertTriangle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { Finding, Severity } from "@/lib/types";

const SEVERITY_VARIANT: Record<Severity, "neutral" | "info" | "warning" | "danger"> = {
  info: "neutral",
  low: "info",
  medium: "warning",
  high: "danger",
  critical: "danger",
};

export function FindingsList({ findings }: { findings: Finding[] }) {
  if (findings.length === 0) {
    return <p className="text-[13px] text-muted-foreground">The scanner found nothing suspicious.</p>;
  }
  return (
    <ul className="flex flex-col gap-2">
      {findings.map((finding, index) => (
        <li key={index} className="rounded-lg border border-border/60 p-3">
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2">
              <AlertTriangle className="size-4 shrink-0 text-warning-text" strokeWidth={1.75} />
              <span className="text-[13px] font-medium">{finding.title}</span>
            </div>
            <Badge variant={SEVERITY_VARIANT[finding.severity]} className="capitalize">
              {finding.severity}
            </Badge>
          </div>
          <p className="mt-1.5 text-[12px] text-muted-foreground">{finding.detail}</p>
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono">{finding.location}</code>
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono">{finding.rule}</code>
          </div>
          {finding.evidence ? (
            <pre className="mt-2 overflow-x-auto rounded-md bg-secondary/60 p-2 font-mono text-[11px] text-foreground">
              {finding.evidence}
            </pre>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
