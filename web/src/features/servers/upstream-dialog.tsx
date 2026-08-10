"use client";

import { Plus, X } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useInvalidateRegistry } from "@/hooks/queries";
import { api, ApiError } from "@/lib/api";
import type { Transport, Upstream } from "@/lib/types";

/** The API never returns secret values; it echoes this placeholder, and sending it back means "keep". */
const REDACTED = "••••••";

interface SecretRow {
  id: number;
  key: string;
  value: string;
  stored: boolean;
}

interface FormState {
  name: string;
  display_name: string;
  description: string;
  transport: Transport;
  command: string;
  args: string;
  cwd: string;
  url: string;
  enabled: boolean;
  env: SecretRow[];
  headers: SecretRow[];
}

let rowCounter = 0;
function row(key = "", stored = false): SecretRow {
  rowCounter += 1;
  return { id: rowCounter, key, value: "", stored };
}

function initial(upstream: Upstream | null): FormState {
  return {
    name: upstream?.name ?? "",
    display_name: upstream?.display_name ?? "",
    description: upstream?.description ?? "",
    transport: upstream?.transport ?? "stdio",
    command: upstream?.command ?? "",
    args: (upstream?.args ?? []).join(" "),
    cwd: upstream?.cwd ?? "",
    url: upstream?.url ?? "",
    enabled: upstream?.enabled ?? true,
    env: Object.keys(upstream?.env ?? {}).map((key) => row(key, true)),
    headers: Object.keys(upstream?.headers ?? {}).map((key) => row(key, true)),
  };
}

function toMap(rows: SecretRow[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const item of rows) {
    const key = item.key.trim();
    if (!key) continue;
    out[key] = item.stored && item.value === "" ? REDACTED : item.value;
  }
  return out;
}

export function UpstreamDialog({
  upstream,
  open,
  onOpenChange,
}: {
  upstream: Upstream | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const invalidate = useInvalidateRegistry();
  const [form, setForm] = React.useState<FormState>(() => initial(upstream));
  const [busy, setBusy] = React.useState(false);
  const editing = upstream !== null;

  React.useEffect(() => {
    if (open) setForm(initial(upstream));
  }, [open, upstream]);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function submit() {
    setBusy(true);
    const stdio = form.transport === "stdio";
    const payload: Record<string, unknown> = {
      display_name: form.display_name || form.name,
      description: form.description,
      transport: form.transport,
      enabled: form.enabled,
      args: stdio ? form.args.split(" ").filter(Boolean) : [],
      command: stdio ? form.command : null,
      cwd: stdio && form.cwd ? form.cwd : null,
      url: stdio ? null : form.url,
      env: stdio ? toMap(form.env) : {},
      headers: stdio ? {} : toMap(form.headers),
    };
    try {
      const saved = upstream
        ? await api.updateUpstream(upstream.id, payload)
        : await api.createUpstream({ ...payload, name: form.name });
      toast.success(editing ? "Server updated" : "Server added");
      invalidate();
      onOpenChange(false);
      if (!editing) {
        try {
          await api.syncUpstream(saved.id);
          invalidate();
        } catch {
          /* first sync may lag until the process is reachable */
        }
      }
    } catch (error) {
      toast.error(error instanceof ApiError ? error.detail : "Could not save the server");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{editing ? "Edit server" : "Add upstream server"}</DialogTitle>
          <DialogDescription>
            Toolgate connects to this MCP server and namespaces its tools as{" "}
            <code className="font-mono">{form.name || "server"}__tool</code>.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          {!editing ? (
            <Field label="Namespace" htmlFor="name">
              <Input
                id="name"
                value={form.name}
                onChange={(event) => set("name", event.target.value.toLowerCase())}
                placeholder="github"
              />
            </Field>
          ) : null}
          <Field label="Display name" htmlFor="display">
            <Input
              id="display"
              value={form.display_name}
              onChange={(event) => set("display_name", event.target.value)}
              placeholder="GitHub"
            />
          </Field>
          <Field label="Transport" htmlFor="transport">
            <Select value={form.transport} onValueChange={(value) => set("transport", value as Transport)}>
              <SelectTrigger id="transport">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="stdio">stdio (subprocess)</SelectItem>
                <SelectItem value="streamable_http">Streamable HTTP</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          {form.transport === "stdio" ? (
            <>
              <Field label="Command" htmlFor="command">
                <Input
                  id="command"
                  value={form.command}
                  onChange={(event) => set("command", event.target.value)}
                  placeholder="/usr/bin/python3"
                  className="font-mono"
                />
              </Field>
              <Field label="Arguments" htmlFor="args">
                <Input
                  id="args"
                  value={form.args}
                  onChange={(event) => set("args", event.target.value)}
                  placeholder="-m my_server --stdio"
                  className="font-mono"
                />
              </Field>
              <Field label="Working directory" htmlFor="cwd">
                <Input
                  id="cwd"
                  value={form.cwd}
                  onChange={(event) => set("cwd", event.target.value)}
                  placeholder="Optional"
                  className="font-mono"
                />
              </Field>
              <SecretRows
                label="Environment variables"
                keyPlaceholder="API_TOKEN"
                rows={form.env}
                onChange={(rows) => set("env", rows)}
              />
            </>
          ) : (
            <>
              <Field label="Endpoint URL" htmlFor="url">
                <Input
                  id="url"
                  value={form.url}
                  onChange={(event) => set("url", event.target.value)}
                  placeholder="https://mcp.example.com/mcp"
                  className="font-mono"
                />
              </Field>
              <SecretRows
                label="Request headers"
                keyPlaceholder="Authorization"
                rows={form.headers}
                onChange={(rows) => set("headers", rows)}
              />
            </>
          )}
          <div className="flex items-center justify-between rounded-lg border border-border/60 px-3 py-2.5">
            <Label htmlFor="enabled">Enabled</Label>
            <Switch id="enabled" checked={form.enabled} onCheckedChange={(value) => set("enabled", value)} />
          </div>
        </div>

        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={busy || (!editing && !form.name)}>
            {editing ? "Save" : "Add & sync"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SecretRows({
  label,
  keyPlaceholder,
  rows,
  onChange,
}: {
  label: string;
  keyPlaceholder: string;
  rows: SecretRow[];
  onChange: (rows: SecretRow[]) => void;
}) {
  const labelId = React.useId();
  function patch(id: number, update: Partial<SecretRow>) {
    onChange(rows.map((item) => (item.id === id ? { ...item, ...update } : item)));
  }
  return (
    <div className="flex flex-col gap-1.5" role="group" aria-labelledby={labelId}>
      <div className="flex items-center justify-between">
        <span id={labelId} className="text-[13px] font-medium">
          {label}
        </span>
        <Button variant="ghost" size="sm" onClick={() => onChange([...rows, row()])}>
          <Plus className="size-3.5" /> Add
        </Button>
      </div>
      {rows.length === 0 ? (
        <p className="text-[12px] text-muted-foreground">
          None. Values are stored server-side and never shown again, and agents never see them.
        </p>
      ) : (
        rows.map((item) => (
          <div key={item.id} className="flex items-center gap-2">
            <Input
              aria-label="Name"
              value={item.key}
              onChange={(event) => patch(item.id, { key: event.target.value })}
              placeholder={keyPlaceholder}
              className="w-2/5 font-mono"
              disabled={item.stored}
            />
            <Input
              aria-label={`Value for ${item.key || "new entry"}`}
              type="password"
              autoComplete="off"
              value={item.value}
              onChange={(event) => patch(item.id, { value: event.target.value })}
              placeholder={item.stored ? "Saved. Leave blank to keep" : "Value"}
              className="flex-1 font-mono"
            />
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Remove ${item.key || "entry"}`}
              onClick={() => onChange(rows.filter((other) => other.id !== item.id))}
            >
              <X className="size-4" />
            </Button>
          </div>
        ))
      )}
    </div>
  );
}

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
    </div>
  );
}
