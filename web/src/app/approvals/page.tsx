"use client";

import { Check, ShieldCheck } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { QueryError } from "@/components/query-error";
import { RiskBadge } from "@/components/risk-badge";
import { ToolStatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ToolDetailDialog } from "@/features/tools/tool-detail-dialog";
import { useApprovals } from "@/hooks/queries";
import { formatRelative } from "@/lib/format";

export default function ApprovalsPage() {
  const approvals = useApprovals();
  const [selected, setSelected] = React.useState<string | null>(null);
  const [open, setOpen] = React.useState(false);

  function review(id: string) {
    setSelected(id);
    setOpen(true);
  }

  return (
    <div>
      <PageHeader
        title="Approval queue"
        description="New tools and post-approval changes wait here until an administrator reviews them."
      />

      {approvals.isError && !approvals.data ? (
        <QueryError what="the approval queue" error={approvals.error} onRetry={() => void approvals.refetch()} />
      ) : approvals.isLoading ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      ) : approvals.data && approvals.data.length > 0 ? (
        <div className="flex flex-col gap-3">
          {approvals.data.map((item) => (
            <Card key={item.tool.id}>
              <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[14px]">{item.tool.exposed_name}</span>
                    <ToolStatusBadge status={item.tool.status} />
                    <RiskBadge level={item.tool.risk_level} score={item.tool.risk_score} />
                    {item.change?.kind === "changed" ? (
                      <Badge variant="warning">definition changed</Badge>
                    ) : item.change?.kind === "new" ? (
                      <Badge variant="info">new tool</Badge>
                    ) : null}
                  </div>
                  <p className="mt-1 line-clamp-2 text-[13px] text-muted-foreground">{item.tool.description}</p>
                  {item.top_findings.length > 0 ? (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {item.top_findings.map((finding, index) => (
                        <Badge key={index} variant="danger">
                          {finding.title}
                        </Badge>
                      ))}
                    </div>
                  ) : null}
                  <p className="mt-2 text-[11px] text-muted-foreground">
                    {item.tool.upstream_name} · detected {formatRelative(item.tool.status_changed_at)}
                  </p>
                </div>
                <Button onClick={() => review(item.tool.id)}>
                  {item.tool.status === "quarantined" ? "Review change" : "Review"}
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <Card>
          <EmptyState
            icon={ShieldCheck}
            title="Nothing to review"
            description="Every discovered tool has been approved or rejected. New or changed tools will appear here automatically."
            action={
              <span className="inline-flex items-center gap-1.5 text-[12px] text-success-text">
                <Check className="size-3.5" /> All caught up
              </span>
            }
          />
        </Card>
      )}

      <ToolDetailDialog toolId={selected} open={open} onOpenChange={setOpen} />
    </div>
  );
}
