"use client";

import { ChevronLeft, ChevronRight, Search, Wrench } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { QueryError } from "@/components/query-error";
import { RiskBadge } from "@/components/risk-badge";
import { ToolStatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ToolDetailDialog } from "@/features/tools/tool-detail-dialog";
import { useTools } from "@/hooks/queries";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { formatRelative } from "@/lib/format";
import type { RiskLevel, ToolStatus } from "@/lib/types";

const STATUSES: (ToolStatus | "all")[] = ["all", "pending", "approved", "quarantined", "rejected"];
const RISKS: (RiskLevel | "all")[] = ["all", "critical", "high", "medium", "low", "none"];
const PAGE_SIZE = 25;

export default function ToolsPage() {
  const [status, setStatus] = React.useState<ToolStatus | "all">("all");
  const [risk, setRisk] = React.useState<RiskLevel | "all">("all");
  const [query, setQuery] = React.useState("");
  const [selected, setSelected] = React.useState<string | null>(null);
  const [open, setOpen] = React.useState(false);
  const [offset, setOffset] = React.useState(0);
  const search = useDebouncedValue(query.trim(), 250);

  React.useEffect(() => setOffset(0), [status, risk, search]);

  const tools = useTools({
    ...(status !== "all" ? { status } : {}),
    ...(risk !== "all" ? { risk } : {}),
    ...(search ? { q: search } : {}),
    limit: PAGE_SIZE,
    offset,
  });
  const total = tools.data?.total ?? 0;

  function openTool(id: string) {
    setSelected(id);
    setOpen(true);
  }

  return (
    <div>
      <PageHeader
        title="Tool inventory"
        description="Every tool discovered across your upstreams, scored for risk and pinned by hash."
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-52 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label="Search tools or servers"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search tools or servers"
            className="rounded-full border-transparent bg-secondary pl-9"
          />
        </div>
        <Select value={status} onValueChange={(value) => setStatus(value as ToolStatus | "all")}>
          <SelectTrigger className="w-40" aria-label="Filter by status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUSES.map((value) => (
              <SelectItem key={value} value={value} className="capitalize">
                {value === "all" ? "All statuses" : value}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={risk} onValueChange={(value) => setRisk(value as RiskLevel | "all")}>
          <SelectTrigger className="w-36" aria-label="Filter by risk">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {RISKS.map((value) => (
              <SelectItem key={value} value={value} className="capitalize">
                {value === "all" ? "All risk" : value}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <Card className="overflow-hidden p-0">
        {tools.isError && !tools.data ? (
          <div className="p-4">
            <QueryError what="tools" error={tools.error} onRetry={() => void tools.refetch()} />
          </div>
        ) : tools.isLoading ? (
          <div className="flex flex-col gap-px p-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-10" />
            ))}
          </div>
        ) : tools.data && tools.data.items.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Tool</TableHead>
                <TableHead>Server</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Risk</TableHead>
                <TableHead>Findings</TableHead>
                <TableHead>Last seen</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tools.data.items.map((tool) => (
                <TableRow
                  key={tool.id}
                  className="cursor-pointer"
                  onClick={() => openTool(tool.id)}
                  tabIndex={0}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") openTool(tool.id);
                  }}
                >
                  <TableCell>
                    <div className="font-mono text-[13px]">{tool.exposed_name}</div>
                    <div className="max-w-md truncate text-[12px] text-muted-foreground">{tool.description}</div>
                  </TableCell>
                  <TableCell className="text-[13px] text-muted-foreground">{tool.upstream_name}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1.5">
                      <ToolStatusBadge status={tool.status} />
                      {tool.has_drift ? <Badge variant="warning">drift</Badge> : null}
                    </div>
                  </TableCell>
                  <TableCell>
                    <RiskBadge level={tool.risk_level} score={tool.risk_score} />
                  </TableCell>
                  <TableCell className="tabular text-[13px]">{tool.finding_count}</TableCell>
                  <TableCell className="text-[12px] text-muted-foreground">
                    {formatRelative(tool.last_seen_at)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <EmptyState
            icon={Wrench}
            title="No tools match"
            description="Adjust the filters, or add an upstream server and sync it to discover tools."
          />
        )}
      </Card>

      {total > PAGE_SIZE ? (
        <nav aria-label="Pagination" className="mt-3 flex items-center justify-between text-[12px] text-muted-foreground">
          <span className="tabular">
            {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
          </span>
          <div className="flex items-center gap-1">
            <Button
              variant="secondary"
              size="sm"
              disabled={offset === 0}
              onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))}
            >
              <ChevronLeft className="size-3.5" /> Previous
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset((value) => value + PAGE_SIZE)}
            >
              Next <ChevronRight className="size-3.5" />
            </Button>
          </div>
        </nav>
      ) : null}

      <ToolDetailDialog toolId={selected} open={open} onOpenChange={setOpen} />
    </div>
  );
}
