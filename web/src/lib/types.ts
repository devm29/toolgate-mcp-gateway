export type ToolStatus = "pending" | "approved" | "quarantined" | "rejected";
export type UpstreamStatus = "pending" | "connected" | "degraded" | "disabled";
export type Transport = "stdio" | "streamable_http";
export type RiskLevel = "none" | "low" | "medium" | "high" | "critical";
export type Severity = "info" | "low" | "medium" | "high" | "critical";
export const DECISIONS = [
  "allowed",
  "denied",
  "quarantined",
  "rate_limited",
  "unknown_tool",
  "upstream_error",
] as const;
export type Decision = (typeof DECISIONS)[number];

export interface ToolCounts {
  total: number;
  approved: number;
  pending: number;
  quarantined: number;
  rejected: number;
}

export interface Upstream {
  id: string;
  name: string;
  display_name: string;
  description: string;
  transport: Transport;
  command: string | null;
  args: string[];
  env: Record<string, string>;
  cwd: string | null;
  url: string | null;
  headers: Record<string, string>;
  enabled: boolean;
  status: UpstreamStatus;
  last_error: string | null;
  last_synced_at: string | null;
  created_at: string;
  tool_counts: ToolCounts;
  max_risk_score: number;
}

export interface ToolSummary {
  id: string;
  exposed_name: string;
  upstream_id: string;
  upstream_name: string;
  upstream_tool_name: string;
  title: string | null;
  description: string;
  status: ToolStatus;
  risk_score: number;
  risk_level: RiskLevel;
  finding_count: number;
  has_drift: boolean;
  removed: boolean;
  first_seen_at: string;
  last_seen_at: string;
  status_changed_at: string;
  approved_at: string | null;
  approved_by: string | null;
}

export interface Finding {
  rule: string;
  severity: Severity;
  title: string;
  detail: string;
  location: string;
  evidence: string | null;
}

export interface ClassifierVerdict {
  label: "benign" | "suspicious" | "malicious";
  confidence: number;
  rationale: string;
  model: string;
}

export interface ScanReport {
  tool_name: string;
  definition_hash: string;
  score: number;
  level: RiskLevel;
  findings: Finding[];
  classifier: ClassifierVerdict | null;
  scanner_version: string;
  scanned_at: string;
}

export interface Pin {
  id: string;
  sha256: string;
  approved_by: string;
  note: string;
  created_at: string;
}

export interface ToolChange {
  id: string;
  kind: "new" | "changed" | "removed";
  previous_hash: string | null;
  new_hash: string;
  detected_at: string;
  resolved_at: string | null;
  resolution: string | null;
  resolved_by: string | null;
}

export interface ToolDefinitionBody {
  name: string;
  title: string | null;
  description: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown> | null;
  annotations: Record<string, unknown> | null;
}

export interface ToolDetail extends ToolSummary {
  current_hash: string;
  approved_hash: string | null;
  current_definition: ToolDefinitionBody;
  approved_definition: ToolDefinitionBody | null;
  scan_report: ScanReport | null;
  pins: Pin[];
  changes: ToolChange[];
}

export interface DiffLine {
  kind: "equal" | "added" | "removed";
  before_line: number | null;
  after_line: number | null;
  text: string;
}

export interface DiffSection {
  field: string;
  changed: boolean;
  before: string | null;
  after: string | null;
  lines: DiffLine[];
}

export interface DefinitionDiff {
  base_hash: string | null;
  head_hash: string;
  sections: DiffSection[];
}

export interface ApprovalItem {
  tool: ToolSummary;
  change: ToolChange | null;
  top_findings: Finding[];
}

export interface RateLimit {
  capacity: number;
  refill_per_minute: number;
}

export interface PolicyRule {
  id: string;
  effect: "allow" | "deny";
  principals: string[];
  tools: string[];
  arguments: Record<string, unknown> | null;
  rate_limit: RateLimit | null;
  description: string;
}

export interface Policy {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  rules: PolicyRule[];
  version: number;
  created_at: string;
  updated_at: string;
}

export interface PolicyDecision {
  allowed: boolean;
  reason: string;
  matched: { policy_name: string; rule_id: string; effect: string }[];
  violations: string[];
  rate_limits: { key: string; rule: { policy_name: string; rule_id: string } }[];
}

export interface AuditEvent {
  id: number;
  occurred_at: string;
  request_id: string;
  principal: string;
  client_id: string | null;
  tool_name: string;
  upstream: string | null;
  upstream_tool: string | null;
  decision: Decision;
  reason: string;
  arguments: Record<string, unknown>;
  latency_ms: number;
  is_error: boolean;
  trace_id: string | null;
}

export interface HourlyBucket {
  hour: string;
  allowed: number;
  blocked: number;
  errors: number;
}

export interface ToolUsage {
  tool_name: string;
  calls: number;
  blocked: number;
}

export interface AuditStats {
  window_hours: number;
  total: number;
  allowed: number;
  blocked: number;
  errors: number;
  p95_latency_ms: number;
  by_decision: Partial<Record<Decision, number>>;
  hourly: HourlyBucket[];
  top_tools: ToolUsage[];
}

export interface Overview {
  upstreams: number;
  upstreams_connected: number;
  tools_total: number;
  tools_exposed: number;
  awaiting_review: number;
  quarantined: number;
  by_status: Record<ToolStatus, number>;
  by_risk: Record<RiskLevel, number>;
  traffic: AuditStats;
}

export interface OAuthClient {
  client_id: string;
  client_name: string;
  redirect_uris: string[];
  grant_types: string[];
  token_endpoint_auth_method: string;
  scope: string;
  is_active: boolean;
}

export interface PrincipalInfo {
  id: string;
  label: string;
  kind: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface CursorPage<T> {
  items: T[];
  next_cursor: string | null;
}
