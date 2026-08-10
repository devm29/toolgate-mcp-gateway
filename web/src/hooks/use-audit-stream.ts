"use client";

import * as React from "react";

import type { AuditEvent } from "@/lib/types";

const MAX_EVENTS = 200;

export type StreamState = "connecting" | "live" | "error";

export function useAuditStream(enabled: boolean) {
  const [events, setEvents] = React.useState<AuditEvent[]>([]);
  const [state, setState] = React.useState<StreamState>("connecting");

  React.useEffect(() => {
    if (!enabled) return;
    setState("connecting");
    const source = new EventSource("/api/gateway/v1/audit/stream");
    source.addEventListener("open", () => setState("live"));
    source.addEventListener("audit", (event) => {
      try {
        const parsed = JSON.parse((event as MessageEvent<string>).data) as AuditEvent;
        setEvents((prev) => {
          if (prev.some((item) => item.id === parsed.id)) return prev;
          return [parsed, ...prev].slice(0, MAX_EVENTS);
        });
      } catch {
        /* ignore malformed frame */
      }
    });
    // EventSource retries on its own (and resends Last-Event-ID); until it reopens, the feed is not live.
    source.addEventListener("error", () => setState("error"));
    return () => source.close();
  }, [enabled]);

  const clear = React.useCallback(() => setEvents([]), []);
  return { events, state, clear };
}
