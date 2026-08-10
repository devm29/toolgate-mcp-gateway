import { CircleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";

/** Shown in place of a page's content when its data could not be loaded, instead of an endless skeleton. */
export function QueryError({ error, onRetry, what }: { error: unknown; onRetry: () => void; what: string }) {
  const detail = error instanceof ApiError ? error.detail : "The console could not reach the Toolgate API.";
  return (
    <div
      role="alert"
      className="flex flex-col items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-5 sm:flex-row sm:items-center"
    >
      <CircleAlert className="size-5 shrink-0 text-danger-text" strokeWidth={1.75} aria-hidden />
      <div className="flex flex-1 flex-col gap-0.5">
        <p className="text-[14px] font-medium">Could not load {what}</p>
        <p className="text-[13px] text-muted-foreground">{detail}</p>
      </div>
      <Button variant="outline" size="sm" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}
