"use client";

import { Activity, CircleDot, History, Pause, Play, Search, Trash2 } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { DecisionBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuditLog } from "@/hooks/queries";
import { useAuditStream } from "@/hooks/use-audit-stream";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import type { AuditQuery } from "@/lib/api";
import { formatTime } from "@/lib/format";
import { DECISIONS, type AuditEvent, type Decision } from "@/lib/types";
import { cn } from "@/lib/utils";

const DECISION_LABEL: Record<Decision, string> = {
  allowed: "Allowed",
  denied: "Denied",
  quarantined: "Quarantined",
  rate_limited: "Rate limited",
  unknown_tool: "Unknown tool",
  upstream_error: "Upstream error",
};

export default function ActivityPage() {
  const [view, setView] = React.useState<"live" | "history">("live");

  return (
    <div>
      <PageHeader
        title="Activity"
        description="Every tools/call with its decision, latency and upstream. Arguments are redacted before storage."
        actions={
          <Tabs value={view} onValueChange={(value) => setView(value === "history" ? "history" : "live")}>
            <TabsList>
              <TabsTrigger value="live">Live</TabsTrigger>
              <TabsTrigger value="history">History</TabsTrigger>
            </TabsList>
          </Tabs>
        }
      />
      {view === "live" ? <LiveFeed /> : <AuditHistory />}
    </div>
  );
}

function LiveFeed() {
  const [live, setLive] = React.useState(true);
  const { events, state, clear } = useAuditStream(live);

  return (
    <>
      <div className="mb-3 flex items-center gap-2">
        <Badge variant={!live ? "neutral" : state === "live" ? "success" : state === "error" ? "danger" : "warning"}>
          <CircleDot className={cn("size-3", live && state === "live" && "animate-pulse motion-reduce:animate-none")} />
          {!live ? "Paused" : state === "live" ? "Live" : state === "error" ? "Reconnecting" : "Connecting"}
        </Badge>
        <Button variant="secondary" size="sm" onClick={() => setLive((value) => !value)}>
          {live ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
          {live ? "Pause" : "Resume"}
        </Button>
        <Button variant="ghost" size="sm" onClick={clear} disabled={events.length === 0}>
          <Trash2 className="size-3.5" /> Clear
        </Button>
      </div>
      <Card className="overflow-hidden p-0">
        {events.length === 0 ? (
          <EmptyState
            icon={Activity}
            title="Waiting for calls"
            description="Point an MCP agent at the gateway and call a tool. Events will appear here in real time."
          />
        ) : (
          <ul className="divide-y divide-border/60" aria-live="polite">
            {events.map((event) => (
              <EventRow key={event.id} event={event} />
            ))}
          </ul>
        )}
      </Card>
      {events.length > 0 ? (
        <p className="mt-3 text-[12px] text-muted-foreground">
          Showing the {events.length} most recent calls. Reconnects replay anything missed from Postgres.
        </p>
      ) : null}
    </>
  );
}

function AuditHistory() {
  const [decision, setDecision] = React.useState<Decision | "all">("all");
  const [tool, setTool] = React.useState("");
  const [principal, setPrincipal] = React.useState("");
  const debouncedTool = useDebouncedValue(tool.trim(), 300);
  const debouncedPrincipal = useDebouncedValue(principal.trim(), 300);
  const filters: AuditQuery = {
    ...(decision !== "all" ? { decision } : {}),
    ...(debouncedTool ? { tool: debouncedTool } : {}),
    ...(debouncedPrincipal ? { principal: debouncedPrincipal } : {}),
  };
  const log = useAuditLog(filters);
  const events = log.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative min-w-48 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label="Filter by exact tool name"
            value={tool}
            onChange={(event) => setTool(event.target.value)}
            placeholder="Tool, e.g. github__create_issue"
            className="rounded-full border-transparent bg-secondary pl-9 font-mono"
          />
        </div>
        <Input
          aria-label="Filter by principal"
          value={principal}
          onChange={(event) => setPrincipal(event.target.value)}
          placeholder="Principal, e.g. user:alice"
          className="w-72 font-mono"
        />
        <Select value={decision} onValueChange={(value) => setDecision(value as Decision | "all")}>
          <SelectTrigger className="w-44" aria-label="Filter by decision">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All decisions</SelectItem>
            {DECISIONS.map((value) => (
              <SelectItem key={value} value={value}>
                {DECISION_LABEL[value]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <Card className="overflow-hidden p-0">
        {log.isLoading ? (
          <div className="flex flex-col gap-px p-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-10" />
            ))}
          </div>
        ) : events.length === 0 ? (
          <EmptyState
            icon={History}
            title="No calls match"
            description="Change the filters, or wait for agents to call tools through the gateway."
          />
        ) : (
          <ul className="divide-y divide-border/60">
            {events.map((event) => (
              <EventRow key={event.id} event={event} expandable />
            ))}
          </ul>
        )}
      </Card>
      {log.hasNextPage ? (
        <div className="mt-3 flex justify-center">
          <Button variant="secondary" size="sm" disabled={log.isFetchingNextPage} onClick={() => void log.fetchNextPage()}>
            {log.isFetchingNextPage ? "Loading…" : "Load older calls"}
          </Button>
        </div>
      ) : null}
    </>
  );
}

function EventRow({ event, expandable = false }: { event: AuditEvent; expandable?: boolean }) {
  const summary = (
    <>
      <span className="w-20 shrink-0 text-[12px] text-muted-foreground tabular">{formatTime(event.occurred_at)}</span>
      <span className="w-32 shrink-0">
        <DecisionBadge decision={event.decision} />
      </span>
      <span className="min-w-0 flex-1 truncate font-mono">{event.tool_name}</span>
      <span className="hidden w-40 shrink-0 truncate text-[12px] text-muted-foreground sm:block">{event.principal}</span>
      <span className="w-16 shrink-0 text-right text-[12px] text-muted-foreground tabular">
        {event.latency_ms.toFixed(0)} ms
      </span>
    </>
  );
  if (!expandable) {
    return <li className="flex items-center gap-3 px-4 py-2.5 text-[13px]">{summary}</li>;
  }
  return (
    <li>
      <details className="group">
        <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-2.5 text-[13px] hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-ring">
          {summary}
        </summary>
        <div className="flex flex-col gap-2 border-t border-border/60 bg-secondary/40 px-4 py-3 text-[12px]">
          <p>
            <span className="font-medium">Reason: </span>
            <span className="text-muted-foreground">{event.reason || "—"}</span>
          </p>
          <p className="text-muted-foreground">
            {event.upstream ? `${event.upstream} · ${event.upstream_tool ?? ""} · ` : ""}
            {event.client_id ? `client ${event.client_id} · ` : ""}
            {event.trace_id ? `trace ${event.trace_id}` : "no trace"}
          </p>
          <pre className="overflow-x-auto rounded-lg border border-border/60 bg-background p-2 font-mono">
            {JSON.stringify(event.arguments, null, 2)}
          </pre>
        </div>
      </details>
    </li>
  );
}
