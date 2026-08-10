"use client";

import { Activity, Gauge, Server, ShieldAlert, ShieldCheck, Wrench } from "lucide-react";
import Link from "next/link";

import { PageHeader } from "@/components/page-header";
import { QueryError } from "@/components/query-error";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { KpiTile } from "@/components/kpi-tile";
import { DecisionBadge } from "@/components/status-badge";
import { TrafficChart } from "@/features/overview/traffic-chart";
import { useOverview } from "@/hooks/queries";
import { formatNumber } from "@/lib/format";
import { DECISIONS, type RiskLevel } from "@/lib/types";

const RISK_ORDER: RiskLevel[] = ["critical", "high", "medium", "low", "none"];
const RISK_COLOR: Record<RiskLevel, string> = {
  critical: "bg-destructive",
  high: "bg-destructive/70",
  medium: "bg-warning",
  low: "bg-primary",
  none: "bg-success",
};

export default function OverviewPage() {
  const overview = useOverview();
  const { data } = overview;

  return (
    <div>
      <PageHeader title="Overview" description="Health of the gateway and the last 24 hours of traffic." />

      {overview.isError && !data ? (
        <QueryError what="the overview" error={overview.error} onRetry={() => void overview.refetch()} />
      ) : !data ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      ) : (
        <>
          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <KpiTile
              label="Upstream servers"
              value={data.upstreams}
              hint={`${data.upstreams_connected} connected`}
              icon={Server}
              tone={data.upstreams_connected < data.upstreams ? "danger" : "success"}
            />
            <KpiTile
              label="Tools exposed"
              value={data.tools_exposed}
              hint={`of ${data.tools_total} discovered`}
              icon={Wrench}
            />
            <KpiTile
              label="Awaiting review"
              value={data.awaiting_review}
              hint={`${data.quarantined} quarantined`}
              icon={ShieldAlert}
              tone={data.awaiting_review > 0 ? "danger" : "success"}
            />
            <KpiTile
              label="Calls blocked (24h)"
              value={formatNumber(data.traffic.blocked)}
              hint={`${formatNumber(data.traffic.allowed)} allowed`}
              icon={ShieldCheck}
              tone={data.traffic.blocked > 0 ? "danger" : "default"}
            />
          </section>

          <section className="mt-6 grid gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader className="flex-row items-center justify-between">
                <CardTitle>Call volume</CardTitle>
                <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
                  <Legend className="bg-chart-5" label="Allowed" />
                  <Legend className="bg-destructive" label="Blocked" />
                  <Legend className="bg-chart-4" label="Errors" />
                </div>
              </CardHeader>
              <CardContent>
                <TrafficChart data={data.traffic.hourly} />
                <div className="mt-3 flex items-center gap-6 text-[12px] text-muted-foreground">
                  <span className="inline-flex items-center gap-1.5">
                    <Gauge className="size-3.5" /> p95 {data.traffic.p95_latency_ms.toFixed(0)} ms
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <Activity className="size-3.5" /> {formatNumber(data.traffic.total)} calls
                  </span>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Risk distribution</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                {RISK_ORDER.map((level) => {
                  const count = data.by_risk[level] ?? 0;
                  const pct = data.tools_total > 0 ? (count / data.tools_total) * 100 : 0;
                  return (
                    <div key={level} className="flex flex-col gap-1">
                      <div className="flex items-center justify-between text-[12px]">
                        <span className="capitalize text-muted-foreground">{level}</span>
                        <span className="tabular">{count}</span>
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                        <div className={`h-full rounded-full ${RISK_COLOR[level]}`} style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  );
                })}
              </CardContent>
            </Card>
          </section>

          <section className="mt-6 grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader className="flex-row items-center justify-between">
                <CardTitle>Most-called tools</CardTitle>
                <Button asChild variant="ghost" size="sm">
                  <Link href="/activity">View activity</Link>
                </Button>
              </CardHeader>
              <CardContent className="flex flex-col">
                {data.traffic.top_tools.length === 0 ? (
                  <p className="py-4 text-[13px] text-muted-foreground">No calls recorded yet.</p>
                ) : (
                  data.traffic.top_tools.map((tool) => (
                    <div
                      key={tool.tool_name}
                      className="flex items-center justify-between border-b border-border/60 py-2 last:border-0"
                    >
                      <span className="font-mono text-[13px]">{tool.tool_name}</span>
                      <span className="flex items-center gap-3 text-[12px] text-muted-foreground tabular">
                        {tool.blocked > 0 ? (
                          <span className="text-destructive">{tool.blocked} blocked</span>
                        ) : null}
                        {tool.calls} calls
                      </span>
                    </div>
                  ))
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Decisions (24h)</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                {DECISIONS.map((decision) => ({ decision, count: data.traffic.by_decision[decision] ?? 0 }))
                  .filter(({ count }) => count > 0)
                  .map(({ decision, count }) => (
                    <div key={decision} className="flex items-center justify-between py-1">
                      <DecisionBadge decision={decision} />
                      <span className="text-[13px] tabular">{formatNumber(count)}</span>
                    </div>
                  ))}
                {data.traffic.total === 0 ? (
                  <p className="py-4 text-[13px] text-muted-foreground">Run the demo agent to see decisions here.</p>
                ) : null}
              </CardContent>
            </Card>
          </section>
        </>
      )}
    </div>
  );
}

function Legend({ className, label }: { className: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`size-2 rounded-full ${className}`} />
      {label}
    </span>
  );
}
