"use client";

import * as React from "react";

import type { HourlyBucket } from "@/lib/types";

export function TrafficChart({ data }: { data: HourlyBucket[] }) {
  const width = 640;
  const height = 160;
  const pad = { top: 12, right: 8, bottom: 20, left: 8 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const max = Math.max(1, ...data.map((b) => b.allowed + b.blocked + b.errors));
  const barGap = 3;
  const barW = Math.max(2, plotW / Math.max(1, data.length) - barGap);
  const labelEvery = Math.max(1, Math.ceil(data.length / 6));

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label="Hourly call volume">
      {[0.25, 0.5, 0.75, 1].map((t) => (
        <line
          key={t}
          x1={pad.left}
          x2={width - pad.right}
          y1={pad.top + plotH * (1 - t)}
          y2={pad.top + plotH * (1 - t)}
          className="stroke-border"
          strokeDasharray="3 3"
          strokeWidth={1}
        />
      ))}
      {data.map((bucket, index) => {
        const total = bucket.allowed + bucket.blocked + bucket.errors;
        const x = pad.left + index * (barW + barGap);
        let y = pad.top + plotH;
        const segments: React.ReactNode[] = [];
        for (const [key, value, cls] of [
          ["allowed", bucket.allowed, "fill-chart-5"],
          ["blocked", bucket.blocked, "fill-destructive"],
          ["errors", bucket.errors, "fill-chart-4"],
        ] as const) {
          const h = (value / max) * plotH;
          if (h <= 0) continue;
          y -= h;
          segments.push(<rect key={key} x={x} y={y} width={barW} height={h} rx={1.5} className={cls} />);
        }
        return (
          <g key={bucket.hour}>
            {total === 0 ? (
              <rect x={x} y={pad.top + plotH - 2} width={barW} height={2} rx={1} className="fill-border" />
            ) : (
              segments
            )}
            {index % labelEvery === 0 ? (
              <text x={x + barW / 2} y={height - 6} textAnchor="middle" className="fill-muted-foreground text-[9px]">
                {new Date(bucket.hour).getHours()}h
              </text>
            ) : null}
          </g>
        );
      })}
    </svg>
  );
}
