"use client";

import { Play } from "lucide-react";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { usePrincipals, useTools } from "@/hooks/queries";
import { api, ApiError } from "@/lib/api";
import type { PolicyDecision } from "@/lib/types";

export function PolicySimulator() {
  const principals = usePrincipals();
  const tools = useTools({ status: "approved", limit: 200 });
  const [principal, setPrincipal] = React.useState("user:alice");
  const [tool, setTool] = React.useState("");
  const [args, setArgs] = React.useState("{}");
  const [result, setResult] = React.useState<PolicyDecision | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (!tool && tools.data?.items[0]) setTool(tools.data.items[0].exposed_name);
  }, [tool, tools.data]);

  async function run() {
    setBusy(true);
    setError(null);
    let parsed: unknown;
    try {
      parsed = JSON.parse(args || "{}");
    } catch {
      setError("Arguments must be valid JSON");
      setBusy(false);
      return;
    }
    try {
      const decision = await api.simulate({ principal, tool, arguments: parsed });
      setResult(decision);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Simulation failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="sim-principal">Principal</Label>
          <Select value={principal} onValueChange={setPrincipal}>
            <SelectTrigger id="sim-principal">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(principals.data ?? [{ id: "user:alice", label: "Alice", kind: "user" }]).map((p) => (
                <SelectItem key={p.id} value={p.id}>
                  {p.id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="sim-tool">Tool</Label>
          <Select value={tool} onValueChange={setTool}>
            <SelectTrigger id="sim-tool">
              <SelectValue placeholder="Select a tool" />
            </SelectTrigger>
            <SelectContent>
              {(tools.data?.items ?? []).map((t) => (
                <SelectItem key={t.id} value={t.exposed_name}>
                  {t.exposed_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="sim-args">Arguments (JSON)</Label>
        <Textarea id="sim-args" value={args} onChange={(event) => setArgs(event.target.value)} rows={4} />
      </div>
      {error ? <p className="text-[12px] text-destructive">{error}</p> : null}
      <div>
        <Button onClick={run} disabled={busy || !tool}>
          <Play className="size-3.5" /> Evaluate
        </Button>
      </div>

      {result ? (
        <div className="rounded-xl border border-border/60 p-4">
          <div className="flex items-center gap-2">
            <Badge variant={result.allowed ? "success" : "danger"}>{result.allowed ? "Allowed" : "Denied"}</Badge>
            <span className="text-[13px]">{result.reason}</span>
          </div>
          {result.violations.length > 0 ? (
            <ul className="mt-2 flex flex-col gap-1 text-[12px] text-destructive">
              {result.violations.map((violation, index) => (
                <li key={index} className="font-mono">
                  {violation}
                </li>
              ))}
            </ul>
          ) : null}
          {result.matched.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {result.matched.map((rule, index) => (
                <Badge key={index} variant={rule.effect === "deny" ? "danger" : "info"}>
                  {rule.policy_name}/{rule.rule_id}
                </Badge>
              ))}
            </div>
          ) : null}
          {result.rate_limits.length > 0 ? (
            <p className="mt-2 text-[12px] text-muted-foreground">
              Rate limited by {result.rate_limits.map((rl) => `${rl.rule.policy_name}/${rl.rule.rule_id}`).join(", ")}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
