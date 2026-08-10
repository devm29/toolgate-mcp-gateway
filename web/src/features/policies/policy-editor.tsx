"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { z } from "zod";

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
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { keys } from "@/hooks/queries";
import { api, ApiError } from "@/lib/api";
import type { Policy, PolicyRule } from "@/lib/types";

interface RuleDraft {
  key: string;
  id: string;
  effect: "allow" | "deny";
  principals: string;
  tools: string;
  description: string;
  rateLimited: boolean;
  capacity: string;
  refill: string;
  arguments: string;
}

const TEMPLATE: PolicyRule[] = [
  {
    id: "allow-reads",
    effect: "allow",
    principals: ["*"],
    tools: ["weather__*"],
    arguments: null,
    rate_limit: { capacity: 30, refill_per_minute: 60 },
    description: "Low-risk read tools for everyone",
  },
];

const fieldErrorSchema = z.array(z.object({ loc: z.array(z.union([z.string(), z.number()])), msg: z.string() }));

let draftCounter = 0;
function nextKey(): string {
  draftCounter += 1;
  return `rule-${draftCounter}`;
}

function toDraft(rule: PolicyRule): RuleDraft {
  return {
    key: nextKey(),
    id: rule.id,
    effect: rule.effect,
    principals: rule.principals.join(", "),
    tools: rule.tools.join(", "),
    description: rule.description,
    rateLimited: rule.rate_limit !== null,
    capacity: String(rule.rate_limit?.capacity ?? 10),
    refill: String(rule.rate_limit?.refill_per_minute ?? 10),
    arguments: rule.arguments ? JSON.stringify(rule.arguments, null, 2) : "",
  };
}

function splitList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function fromDraft(draft: RuleDraft, index: number): PolicyRule {
  let args: Record<string, unknown> | null = null;
  if (draft.arguments.trim()) {
    const label = draft.id.trim() || String(index + 1);
    let parsed: unknown;
    try {
      parsed = JSON.parse(draft.arguments);
    } catch {
      throw new Error(`Rule "${label}": argument constraints are not valid JSON`);
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      throw new Error(`Rule "${label}": argument constraints must be a JSON Schema object`);
    }
    args = parsed as Record<string, unknown>;
  }
  return {
    id: draft.id.trim(),
    effect: draft.effect,
    principals: splitList(draft.principals),
    tools: splitList(draft.tools),
    description: draft.description,
    arguments: args,
    rate_limit:
      draft.rateLimited && draft.effect === "allow"
        ? { capacity: Number(draft.capacity), refill_per_minute: Number(draft.refill) }
        : null,
  };
}

function describeLocation(loc: (string | number)[], rules: RuleDraft[]): string {
  const path = loc[0] === "body" ? loc.slice(1) : loc;
  if (path[0] === "rules" && typeof path[1] === "number") {
    const rule = rules[path[1]];
    const label = rule?.id ? `rule "${rule.id}"` : `rule ${path[1] + 1}`;
    const rest = path.slice(2).join(".");
    return rest ? `${label} → ${rest}` : label;
  }
  return path.join(".") || "policy";
}

export function PolicyEditor({
  policy,
  open,
  onOpenChange,
}: {
  policy: Policy | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const client = useQueryClient();
  const [mode, setMode] = React.useState<"form" | "json">("form");
  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [enabled, setEnabled] = React.useState(true);
  const [drafts, setDrafts] = React.useState<RuleDraft[]>([]);
  const [json, setJson] = React.useState("");
  const [errors, setErrors] = React.useState<string[]>([]);
  const [busy, setBusy] = React.useState(false);
  const nameRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    if (!open) return;
    const rules = policy?.rules ?? TEMPLATE;
    setName(policy?.name ?? "");
    setDescription(policy?.description ?? "");
    setEnabled(policy?.enabled ?? true);
    setDrafts(rules.map(toDraft));
    setJson(JSON.stringify(rules, null, 2));
    setMode("form");
    setErrors([]);
  }, [open, policy]);

  function currentRules(): PolicyRule[] {
    if (mode === "json") {
      const parsed: unknown = JSON.parse(json);
      if (!Array.isArray(parsed)) throw new Error("Rules must be a JSON array");
      return parsed as PolicyRule[];
    }
    return drafts.map(fromDraft);
  }

  function switchMode(next: string) {
    if (next !== "form" && next !== "json") return;
    try {
      const rules = currentRules();
      if (next === "json") setJson(JSON.stringify(rules, null, 2));
      else setDrafts(rules.map(toDraft));
      setErrors([]);
      setMode(next);
    } catch (error) {
      setErrors([error instanceof Error ? error.message : "Fix the rules before switching views"]);
    }
  }

  function update(key: string, patch: Partial<RuleDraft>) {
    setDrafts((prev) => prev.map((draft) => (draft.key === key ? { ...draft, ...patch } : draft)));
  }

  async function save() {
    setErrors([]);
    let rules: PolicyRule[];
    try {
      rules = currentRules();
    } catch (error) {
      const message = error instanceof Error ? error.message : "The rules could not be read";
      setErrors([error instanceof SyntaxError ? `Invalid JSON: ${message}` : message]);
      return;
    }
    setBusy(true);
    const payload = { name, description, enabled, rules };
    try {
      if (policy) await api.updatePolicy(policy.id, { ...payload, expected_version: policy.version });
      else await api.createPolicy(payload);
      toast.success(policy ? "Policy saved" : "Policy created");
      void client.invalidateQueries({ queryKey: keys.policies });
      onOpenChange(false);
    } catch (error) {
      if (error instanceof ApiError) {
        const fields = fieldErrorSchema.safeParse(error.extra?.errors);
        setErrors(
          fields.success && fields.data.length > 0
            ? fields.data.map((item) => `${describeLocation(item.loc, drafts)}: ${item.msg}`)
            : [error.detail],
        );
      } else {
        setErrors(["Could not save the policy"]);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        wide
        className="max-h-[85vh] overflow-y-auto focus:outline-none"
        onOpenAutoFocus={(event) => {
          // Radix focuses the first input with its text selected; editing should open on the dialog itself.
          event.preventDefault();
          if (policy) {
            if (event.currentTarget instanceof HTMLElement) event.currentTarget.focus();
          } else {
            nameRef.current?.focus();
          }
        }}
      >
        <DialogHeader>
          <DialogTitle>{policy ? "Edit policy" : "New policy"}</DialogTitle>
          <DialogDescription>
            Deny rules win over allow rules, and a call with no matching allow is denied. Globs match the user
            (user:alice) and the OAuth client (client:tg_…) on each token.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="policy-name">Name</Label>
              <Input id="policy-name" ref={nameRef} value={name} onChange={(event) => setName(event.target.value)} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="policy-enabled">Enabled</Label>
              <div className="flex h-9 items-center">
                <Switch id="policy-enabled" checked={enabled} onCheckedChange={setEnabled} />
              </div>
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="policy-desc">Description</Label>
            <Input id="policy-desc" value={description} onChange={(event) => setDescription(event.target.value)} />
          </div>

          <div className="flex items-center justify-between pt-1">
            <span className="text-[13px] font-medium">Rules</span>
            <Tabs value={mode} onValueChange={switchMode}>
              <TabsList>
                <TabsTrigger value="form">Form</TabsTrigger>
                <TabsTrigger value="json">JSON</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>

          {mode === "json" ? (
            <Textarea
              aria-label="Rules as JSON"
              value={json}
              onChange={(event) => setJson(event.target.value)}
              className="min-h-72"
            />
          ) : (
            <div className="flex flex-col gap-3">
              {drafts.map((draft, index) => (
                <RuleCard
                  key={draft.key}
                  draft={draft}
                  index={index}
                  onChange={(patch) => update(draft.key, patch)}
                  onRemove={() => setDrafts((prev) => prev.filter((item) => item.key !== draft.key))}
                />
              ))}
              <Button
                variant="secondary"
                size="sm"
                className="self-start"
                onClick={() =>
                  setDrafts((prev) => [
                    ...prev,
                    toDraft({
                      id: `rule-${prev.length + 1}`,
                      effect: "allow",
                      principals: ["*"],
                      tools: [],
                      arguments: null,
                      rate_limit: null,
                      description: "",
                    }),
                  ])
                }
              >
                <Plus className="size-3.5" /> Add rule
              </Button>
            </div>
          )}

          {errors.length > 0 ? (
            <div role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-danger-text">
              <p className="font-medium">The policy was not saved. Fix these and try again:</p>
              <ul className="mt-1 list-disc pl-4">
                {errors.map((message) => (
                  <li key={message}>{message}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={save} disabled={busy || !name}>
            {policy ? "Save changes" : "Create policy"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RuleCard({
  draft,
  index,
  onChange,
  onRemove,
}: {
  draft: RuleDraft;
  index: number;
  onChange: (patch: Partial<RuleDraft>) => void;
  onRemove: () => void;
}) {
  const prefix = `${draft.key}-`;
  return (
    <fieldset className="flex flex-col gap-3 rounded-xl border border-border/60 p-3">
      <legend className="sr-only">Rule {index + 1}</legend>
      <div className="grid gap-3 sm:grid-cols-[1fr_140px_auto]">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${prefix}id`}>Rule id</Label>
          <Input
            id={`${prefix}id`}
            value={draft.id}
            onChange={(event) => onChange({ id: event.target.value })}
            className="font-mono"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${prefix}effect`}>Effect</Label>
          <Select value={draft.effect} onValueChange={(value) => onChange({ effect: value === "deny" ? "deny" : "allow" })}>
            <SelectTrigger id={`${prefix}effect`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="allow">Allow</SelectItem>
              <SelectItem value="deny">Deny</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-end">
          <Button variant="ghost" size="icon" className="text-destructive" aria-label={`Remove rule ${draft.id}`} onClick={onRemove}>
            <Trash2 className="size-4" />
          </Button>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${prefix}principals`}>Principals</Label>
          <Input
            id={`${prefix}principals`}
            value={draft.principals}
            onChange={(event) => onChange({ principals: event.target.value })}
            placeholder="user:alice, user:ops"
            className="font-mono"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${prefix}tools`}>Tools</Label>
          <Input
            id={`${prefix}tools`}
            value={draft.tools}
            onChange={(event) => onChange({ tools: event.target.value })}
            placeholder="github__*, crm__lookup_customer"
            className="font-mono"
          />
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${prefix}description`}>Description</Label>
        <Input
          id={`${prefix}description`}
          value={draft.description}
          onChange={(event) => onChange({ description: event.target.value })}
        />
      </div>
      {draft.effect === "allow" ? (
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex h-9 items-center gap-2">
            <Switch
              id={`${prefix}limited`}
              checked={draft.rateLimited}
              onCheckedChange={(value) => onChange({ rateLimited: value })}
            />
            <Label htmlFor={`${prefix}limited`}>Rate limit</Label>
          </div>
          {draft.rateLimited ? (
            <>
              <div className="flex w-28 flex-col gap-1.5">
                <Label htmlFor={`${prefix}capacity`}>Burst</Label>
                <Input
                  id={`${prefix}capacity`}
                  inputMode="numeric"
                  value={draft.capacity}
                  onChange={(event) => onChange({ capacity: event.target.value })}
                />
              </div>
              <div className="flex w-32 flex-col gap-1.5">
                <Label htmlFor={`${prefix}refill`}>Per minute</Label>
                <Input
                  id={`${prefix}refill`}
                  inputMode="decimal"
                  value={draft.refill}
                  onChange={(event) => onChange({ refill: event.target.value })}
                />
              </div>
            </>
          ) : null}
        </div>
      ) : null}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${prefix}arguments`}>
          {draft.effect === "allow" ? "Arguments must match (JSON Schema)" : "Deny only calls matching (JSON Schema)"}
        </Label>
        <Textarea
          id={`${prefix}arguments`}
          value={draft.arguments}
          onChange={(event) => onChange({ arguments: event.target.value })}
          placeholder='{"type": "object", "properties": {"repo": {"enum": ["acme/web"]}}}'
          className="min-h-16"
        />
        <p className="text-[12px] text-muted-foreground">Leave empty to apply the rule to every call.</p>
      </div>
    </fieldset>
  );
}
