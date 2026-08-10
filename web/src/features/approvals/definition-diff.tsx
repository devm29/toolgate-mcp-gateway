"use client";

import { Badge } from "@/components/ui/badge";
import type { DefinitionDiff, DiffLine, DiffSection } from "@/lib/types";
import { cn } from "@/lib/utils";

const FIELD_LABEL: Record<string, string> = {
  name: "Name",
  title: "Title",
  description: "Description",
  input_schema: "Input schema",
  output_schema: "Output schema",
  annotations: "Annotations",
};

interface Cell {
  line: number;
  text: string;
  kind: DiffLine["kind"];
}

interface Row {
  before: Cell | null;
  after: Cell | null;
}

/** Pair a unified diff into aligned rows: unchanged lines sit side by side, and each run of removals is matched
 * against the run of additions that replaced it. */
export function toRows(lines: DiffLine[]): Row[] {
  const rows: Row[] = [];
  let removed: Cell[] = [];
  let added: Cell[] = [];
  const flush = () => {
    for (let i = 0; i < Math.max(removed.length, added.length); i += 1) {
      rows.push({ before: removed[i] ?? null, after: added[i] ?? null });
    }
    removed = [];
    added = [];
  };
  for (const line of lines) {
    if (line.kind === "equal") {
      flush();
      rows.push({
        before: { line: line.before_line ?? 0, text: line.text, kind: "equal" },
        after: { line: line.after_line ?? 0, text: line.text, kind: "equal" },
      });
    } else if (line.kind === "removed") {
      removed.push({ line: line.before_line ?? 0, text: line.text, kind: "removed" });
    } else {
      added.push({ line: line.after_line ?? 0, text: line.text, kind: "added" });
    }
  }
  flush();
  return rows;
}

export function DefinitionDiffView({ diff }: { diff: DefinitionDiff }) {
  const sections = diff.sections.filter((section) => section.changed || section.after !== null);
  const changed = sections.filter((section) => section.changed);
  const firstReview = diff.base_hash === null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted-foreground">
        <span>
          Approved{" "}
          <code className="rounded bg-muted px-1.5 py-0.5 font-mono">{diff.base_hash?.slice(0, 10) ?? "none"}</code>
        </span>
        <span aria-hidden>→</span>
        <span>
          Upstream <code className="rounded bg-muted px-1.5 py-0.5 font-mono">{diff.head_hash.slice(0, 10)}</code>
        </span>
        {firstReview ? (
          <Badge variant="info">First review</Badge>
        ) : changed.length > 0 ? (
          <Badge variant="danger">
            {changed.length} field{changed.length > 1 ? "s" : ""} changed
          </Badge>
        ) : (
          <Badge variant="success">No differences</Badge>
        )}
      </div>
      <p className="text-[12px] text-muted-foreground">
        Invisible characters are shown as ⟦U+XXXX⟧ markers. The model reads them even though most editors hide them.
      </p>
      {sections.map((section) => (
        <DiffFieldBlock key={section.field} section={section} firstReview={firstReview} />
      ))}
    </div>
  );
}

function DiffFieldBlock({ section, firstReview }: { section: DiffSection; firstReview: boolean }) {
  const rows = toRows(section.lines);
  return (
    <div className="overflow-hidden rounded-xl border border-border/60">
      <div className="flex items-center justify-between border-b border-border/60 bg-secondary/60 px-3 py-2">
        <span className="text-[13px] font-medium">{FIELD_LABEL[section.field] ?? section.field}</span>
        {section.changed && !firstReview ? (
          <Badge variant="warning">Changed</Badge>
        ) : (
          <Badge variant="outline">{firstReview ? "New" : "Unchanged"}</Badge>
        )}
      </div>
      <div className="grid grid-cols-2 border-b border-border/60 text-[11px] font-medium text-muted-foreground">
        <div className="border-r border-border/60 px-3 py-1">Approved</div>
        <div className="px-3 py-1">Upstream now</div>
      </div>
      {rows.length === 0 ? (
        <div className="px-3 py-2 font-mono text-[12px] text-muted-foreground">empty</div>
      ) : (
        <div role="table" aria-label={`${FIELD_LABEL[section.field] ?? section.field} comparison`}>
          {rows.map((row, index) => (
            <div key={index} role="row" className="grid grid-cols-2 font-mono text-[12px] leading-relaxed">
              <DiffCell cell={row.before} side="before" />
              <DiffCell cell={row.after} side="after" />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function DiffCell({ cell, side }: { cell: Cell | null; side: "before" | "after" }) {
  const marker = cell?.kind === "removed" ? "−" : cell?.kind === "added" ? "+" : "";
  return (
    <div
      role="cell"
      className={cn(
        "flex min-w-0 gap-2 px-2 py-0.5",
        side === "before" && "border-r border-border/60",
        cell === null && "bg-muted/40",
        cell?.kind === "removed" && "bg-destructive/10",
        cell?.kind === "added" && "bg-success/10",
      )}
    >
      {cell ? (
        <>
          <span className="w-6 shrink-0 select-none text-right text-muted-foreground tabular">{cell.line}</span>
          <span
            aria-label={cell.kind === "removed" ? "removed" : cell.kind === "added" ? "added" : undefined}
            className={cn(
              "w-3 shrink-0 select-none",
              cell.kind === "removed" && "text-danger-text",
              cell.kind === "added" && "text-success-text",
            )}
          >
            {marker}
          </span>
          <span
            className={cn("min-w-0 whitespace-pre-wrap break-words", cell.kind === "equal" && "text-muted-foreground")}
          >
            {cell.text}
          </span>
        </>
      ) : null}
    </div>
  );
}
