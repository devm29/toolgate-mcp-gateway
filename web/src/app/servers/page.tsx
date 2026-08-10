"use client";

import { MoreHorizontal, Plus, RefreshCw, Server, Trash2 } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { QueryError } from "@/components/query-error";
import { UpstreamStatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { UpstreamDialog } from "@/features/servers/upstream-dialog";
import { useInvalidateRegistry, useSyncUpstream, useUpstreams } from "@/hooks/queries";
import { api, ApiError } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import type { Upstream } from "@/lib/types";

export default function ServersPage() {
  const upstreams = useUpstreams();
  const sync = useSyncUpstream();
  const invalidate = useInvalidateRegistry();
  const [editing, setEditing] = React.useState<Upstream | null>(null);
  const [open, setOpen] = React.useState(false);
  const [removing, setRemoving] = React.useState<Upstream | null>(null);

  function add() {
    setEditing(null);
    setOpen(true);
  }

  function edit(upstream: Upstream) {
    setEditing(upstream);
    setOpen(true);
  }

  async function runSync(upstream: Upstream) {
    try {
      await sync.mutateAsync(upstream.id);
      toast.success(`Synced ${upstream.name}`);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.detail : "Sync failed");
    }
  }

  async function remove(upstream: Upstream) {
    try {
      await api.deleteUpstream(upstream.id);
      toast.success("Server removed");
      invalidate();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.detail : "Could not remove the server");
    }
  }

  return (
    <div>
      <PageHeader
        title="Upstream servers"
        description="MCP servers federated behind the gateway, over stdio or Streamable HTTP."
        actions={
          <Button onClick={add}>
            <Plus className="size-4" /> Add server
          </Button>
        }
      />

      {upstreams.isError && !upstreams.data ? (
        <QueryError what="upstream servers" error={upstreams.error} onRetry={() => void upstreams.refetch()} />
      ) : upstreams.isLoading ? (
        <div className="grid gap-3 md:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-32" />
          ))}
        </div>
      ) : upstreams.data && upstreams.data.length > 0 ? (
        <div className="grid gap-3 md:grid-cols-2">
          {upstreams.data.map((upstream) => (
            <Card key={upstream.id}>
              <CardContent className="flex flex-col gap-3 p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-[15px] font-semibold">{upstream.display_name}</span>
                      <Badge variant="outline" className="font-mono">
                        {upstream.name}
                      </Badge>
                    </div>
                    <p className="mt-0.5 text-[12px] text-muted-foreground">
                      {upstream.transport === "stdio" ? "stdio" : "Streamable HTTP"} ·{" "}
                      {upstream.last_synced_at ? `synced ${formatRelative(upstream.last_synced_at)}` : "never synced"}
                    </p>
                  </div>
                  <UpstreamStatusBadge status={upstream.status} />
                </div>

                {upstream.last_error ? (
                  <p className="rounded-md bg-destructive/10 px-2.5 py-1.5 text-[12px] text-destructive">
                    {upstream.last_error}
                  </p>
                ) : null}

                <div className="flex items-center gap-4 text-[12px] text-muted-foreground">
                  <span className="tabular">{upstream.tool_counts.total} tools</span>
                  {upstream.tool_counts.approved > 0 ? (
                    <span className="tabular text-success-text">{upstream.tool_counts.approved} approved</span>
                  ) : null}
                  {upstream.tool_counts.quarantined > 0 ? (
                    <span className="tabular text-destructive">{upstream.tool_counts.quarantined} quarantined</span>
                  ) : null}
                  {upstream.tool_counts.pending > 0 ? (
                    <span className="tabular">{upstream.tool_counts.pending} pending</span>
                  ) : null}
                </div>

                <div className="flex items-center gap-1.5">
                  <Button variant="secondary" size="sm" onClick={() => runSync(upstream)}>
                    <RefreshCw className="size-3.5" /> Sync
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => edit(upstream)}>
                    <MoreHorizontal className="size-3.5" /> Edit
                  </Button>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="ml-auto text-destructive"
                        aria-label="Remove server"
                        onClick={() => setRemoving(upstream)}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Remove server</TooltipContent>
                  </Tooltip>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <Card>
          <EmptyState
            icon={Server}
            title="No servers yet"
            description="Add your first upstream MCP server. Toolgate will connect, pull its tools and scan each one."
            action={
              <Button onClick={add}>
                <Plus className="size-4" /> Add server
              </Button>
            }
          />
        </Card>
      )}

      <UpstreamDialog upstream={editing} open={open} onOpenChange={setOpen} />
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(next) => {
          if (!next) setRemoving(null);
        }}
        title={`Remove ${removing?.display_name ?? "server"}?`}
        description="Its tools, approvals and pins are deleted and agents lose access immediately. The audit log keeps past calls."
        confirmLabel="Remove server"
        onConfirm={async () => {
          if (removing) await remove(removing);
        }}
      />
    </div>
  );
}
