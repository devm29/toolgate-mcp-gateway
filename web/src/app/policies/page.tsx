"use client";

import { Pencil, Plus, SlidersHorizontal, Trash2 } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { QueryError } from "@/components/query-error";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { PolicyEditor } from "@/features/policies/policy-editor";
import { PolicySimulator } from "@/features/policies/policy-simulator";
import { keys, usePolicies } from "@/hooks/queries";
import { api, ApiError } from "@/lib/api";
import type { Policy } from "@/lib/types";

export default function PoliciesPage() {
  const policies = usePolicies();
  const client = useQueryClient();
  const [editing, setEditing] = React.useState<Policy | null>(null);
  const [open, setOpen] = React.useState(false);
  const [deleting, setDeleting] = React.useState<Policy | null>(null);

  function create() {
    setEditing(null);
    setOpen(true);
  }

  function edit(policy: Policy) {
    setEditing(policy);
    setOpen(true);
  }

  async function remove(policy: Policy) {
    try {
      await api.deletePolicy(policy.id);
      toast.success("Policy deleted");
      void client.invalidateQueries({ queryKey: keys.policies });
    } catch (error) {
      toast.error(error instanceof ApiError ? error.detail : "Could not delete the policy");
    }
  }

  return (
    <div>
      <PageHeader
        title="Policies"
        description="Who may call which tools, with argument constraints and rate limits enforced on every call."
        actions={
          <Button onClick={create}>
            <Plus className="size-4" /> New policy
          </Button>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
        <div className="flex flex-col gap-3">
          {policies.isError && !policies.data ? (
            <QueryError what="policies" error={policies.error} onRetry={() => void policies.refetch()} />
          ) : policies.isLoading ? (
            Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-28" />)
          ) : policies.data && policies.data.length > 0 ? (
            policies.data.map((policy) => (
              <Card key={policy.id}>
                <CardContent className="p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-[15px] font-semibold">{policy.name}</span>
                        {policy.enabled ? (
                          <Badge variant="success">enabled</Badge>
                        ) : (
                          <Badge variant="neutral">disabled</Badge>
                        )}
                        <Badge variant="outline">v{policy.version}</Badge>
                      </div>
                      {policy.description ? (
                        <p className="mt-0.5 text-[12px] text-muted-foreground">{policy.description}</p>
                      ) : null}
                    </div>
                    <div className="flex items-center gap-1">
                      <Button variant="ghost" size="icon" aria-label="Edit policy" onClick={() => edit(policy)}>
                        <Pencil className="size-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label="Delete policy"
                        className="text-destructive"
                        onClick={() => setDeleting(policy)}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  </div>
                  <div className="mt-3 flex flex-col gap-1.5">
                    {policy.rules.map((rule) => (
                      <div
                        key={rule.id}
                        className="flex flex-wrap items-center gap-2 rounded-lg border border-border/60 px-2.5 py-1.5 text-[12px]"
                      >
                        <Badge variant={rule.effect === "deny" ? "danger" : "info"}>{rule.effect}</Badge>
                        <code className="font-mono">{rule.principals.join(", ")}</code>
                        <span className="text-muted-foreground">→</span>
                        <code className="font-mono">{rule.tools.join(", ")}</code>
                        {rule.arguments ? <Badge variant="warning">args</Badge> : null}
                        {rule.rate_limit ? (
                          <Badge variant="neutral">
                            {rule.rate_limit.capacity}/{rule.rate_limit.refill_per_minute}pm
                          </Badge>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            ))
          ) : (
            <Card>
              <EmptyState
                icon={SlidersHorizontal}
                title="No policies"
                description="Without a policy every call is denied. Create one to grant access to approved tools."
                action={
                  <Button onClick={create}>
                    <Plus className="size-4" /> New policy
                  </Button>
                }
              />
            </Card>
          )}
        </div>

        <Card className="h-fit lg:sticky lg:top-20">
          <CardHeader>
            <CardTitle>Simulator</CardTitle>
          </CardHeader>
          <CardContent>
            <PolicySimulator />
          </CardContent>
        </Card>
      </div>

      <PolicyEditor policy={editing} open={open} onOpenChange={setOpen} />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(next) => {
          if (!next) setDeleting(null);
        }}
        title={`Delete "${deleting?.name ?? "policy"}"?`}
        description="Calls that only this policy allowed will be denied from the next request on."
        confirmLabel="Delete policy"
        onConfirm={async () => {
          if (deleting) await remove(deleting);
        }}
      />
    </div>
  );
}
