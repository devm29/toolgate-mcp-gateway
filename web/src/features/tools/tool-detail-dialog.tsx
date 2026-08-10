"use client";

import { Check, RefreshCw, ShieldX } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { DefinitionDiffView } from "@/features/approvals/definition-diff";
import { FindingsList } from "@/features/approvals/findings-list";
import { RiskBadge } from "@/components/risk-badge";
import { ToolStatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useInvalidateRegistry, useTool, useToolDiff } from "@/hooks/queries";
import { api, ApiError } from "@/lib/api";
import { formatRelative, revealInvisible, shortHash } from "@/lib/format";

export function ToolDetailDialog({
  toolId,
  open,
  onOpenChange,
}: {
  toolId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const invalidate = useInvalidateRegistry();
  const detail = useTool(toolId ?? "");
  const tool = detail.data;
  // Always fetched: for a first review it renders the full definition with invisible characters revealed.
  const diff = useToolDiff(toolId ?? "", open && Boolean(toolId));
  const needsReview = Boolean(tool && (tool.status !== "approved" || tool.has_drift));
  const [busy, setBusy] = React.useState(false);
  const [rejecting, setRejecting] = React.useState(false);

  async function run(action: () => Promise<unknown>, success: string) {
    setBusy(true);
    try {
      await action();
      toast.success(success);
      invalidate();
      await detail.refetch();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.detail : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent wide className="max-h-[85vh] overflow-y-auto">
        {!tool ? (
          <div className="py-10 text-center text-[13px] text-muted-foreground">Loading…</div>
        ) : (
          <>
            <DialogHeader>
              <div className="flex flex-wrap items-center gap-2">
                <DialogTitle className="font-mono">{tool.exposed_name}</DialogTitle>
                <ToolStatusBadge status={tool.status} />
                <RiskBadge level={tool.risk_level} score={tool.risk_score} />
              </div>
              <DialogDescription>
                {tool.upstream_name} · {tool.upstream_tool_name} · seen {formatRelative(tool.last_seen_at)}
              </DialogDescription>
            </DialogHeader>

            <Tabs key={tool.id} defaultValue={needsReview ? "diff" : "scan"}>
              <TabsList>
                <TabsTrigger value="diff">{tool.approved_hash ? "Changes" : "Review"}</TabsTrigger>
                <TabsTrigger value="scan">Scan ({tool.scan_report?.findings.length ?? 0})</TabsTrigger>
                <TabsTrigger value="definition">Raw JSON</TabsTrigger>
                <TabsTrigger value="history">History</TabsTrigger>
              </TabsList>

              <TabsContent value="scan" className="pt-4">
                {tool.scan_report?.classifier ? (
                  <div className="mb-3 rounded-lg border border-border/60 bg-secondary/50 p-3 text-[12px]">
                    <span className="font-medium capitalize">{tool.scan_report.classifier.label}</span>
                    <span className="text-muted-foreground">
                      {" "}
                      · {(tool.scan_report.classifier.confidence * 100).toFixed(0)}% confidence ·{" "}
                      {tool.scan_report.classifier.model}
                    </span>
                    <p className="mt-1 text-muted-foreground">{tool.scan_report.classifier.rationale}</p>
                  </div>
                ) : null}
                <FindingsList findings={tool.scan_report?.findings ?? []} />
              </TabsContent>

              <TabsContent value="diff" className="pt-4">
                {diff.data ? (
                  <DefinitionDiffView diff={diff.data} />
                ) : (
                  <p className="text-[13px] text-muted-foreground">Loading definition…</p>
                )}
              </TabsContent>

              <TabsContent value="definition" className="pt-4">
                <pre className="overflow-x-auto rounded-lg border border-border/60 bg-secondary/40 p-3 font-mono text-[12px]">
                  {revealInvisible(JSON.stringify(tool.current_definition, null, 2))}
                </pre>
              </TabsContent>

              <TabsContent value="history" className="flex flex-col gap-2 pt-4 text-[13px]">
                {tool.pins.length > 0 ? (
                  <div>
                    <p className="mb-1 text-[12px] font-medium text-muted-foreground">Approvals</p>
                    {tool.pins.map((pin) => (
                      <div key={pin.id} className="flex items-center justify-between border-b border-border/60 py-1.5">
                        <span className="font-mono text-[12px]">{shortHash(pin.sha256)}</span>
                        <span className="text-[12px] text-muted-foreground">
                          {pin.approved_by} · {formatRelative(pin.created_at)}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : null}
                {tool.changes.map((change) => (
                  <div key={change.id} className="flex items-center justify-between border-b border-border/60 py-1.5">
                    <span className="capitalize">{change.kind}</span>
                    <span className="text-[12px] text-muted-foreground">
                      {change.resolution ?? "open"} · {formatRelative(change.detected_at)}
                    </span>
                  </div>
                ))}
              </TabsContent>
            </Tabs>

            <DialogFooter>
              <Button
                variant="secondary"
                size="sm"
                disabled={busy}
                onClick={() => run(() => api.rescanTool(tool.id), "Re-scanned")}
              >
                <RefreshCw className="size-3.5" /> Re-scan
              </Button>
              {tool.status !== "rejected" ? (
                <Button
                  variant="destructive"
                  size="sm"
                  disabled={busy}
                  onClick={() => setRejecting(true)}
                >
                  <ShieldX className="size-3.5" /> Reject
                </Button>
              ) : null}
              {tool.status !== "approved" || tool.has_drift ? (
                <Button
                  size="sm"
                  disabled={busy}
                  onClick={() =>
                    run(() => api.approveTool(tool.id, tool.current_hash, "approved from console"), "Tool approved & pinned")
                  }
                >
                  <Check className="size-3.5" /> Approve & pin
                </Button>
              ) : null}
            </DialogFooter>
            <ConfirmDialog
              open={rejecting}
              onOpenChange={setRejecting}
              title={`Reject ${tool.exposed_name}?`}
              description="Agents stop seeing and calling this tool right away, and its current pin is dropped. You can review and approve it again later."
              reasonLabel="Reason (kept in the change history)"
              reasonPlaceholder="e.g. description asks the model to read SSH keys"
              confirmLabel="Reject tool"
              onConfirm={(reason) => run(() => api.rejectTool(tool.id, reason || "rejected from console"), "Tool rejected")}
            />
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
