export interface Scope {
  user_id?: string;
  agent_id?: string;
  run_id?: string;
}

export type ScopeKind = "user" | "agent" | "run";

export interface ScopeEntry {
  kind: ScopeKind;
  value: string;
  count: number;
  last_seen_at?: string;
}

export interface ScopesPayload {
  provider?: string;
  items: ScopeEntry[];
  totals?: { users?: number; agents?: number; runs?: number };
}

export interface MemoryRecord {
  id: string;
  display_text?: string;
  memory?: string;
  metadata?: Record<string, unknown> | null;
  user_id?: string;
  agent_id?: string;
  run_id?: string;
  pinned?: boolean;
  archived?: boolean;
  score?: number;
  provider?: string;
  created_at?: string;
  updated_at?: string;
  admin_updated_at?: string;
}

export interface StatsTotals {
  memories?: number;
  pinned?: number;
  archived?: number;
  connected_clients?: number;
  configured_clients?: number;
  stale_clients?: number;
}

export interface StatsRuntime {
  api_host?: string;
  api_port?: number;
  provider?: string;
}

export interface StatsPayload {
  provider: string;
  totals?: StatsTotals;
  runtime?: StatsRuntime;
  warning?: string;
}

export type ClientHealth =
  | "connected"
  | "configured"
  | "stale_config"
  | "timeout"
  | "not_configured"
  | "not_detected";

export interface ClientIntegration {
  target: string;
  kind?: string;
  path?: string;
  launcher?: string;
  command?: string;
  expected_launcher?: string;
  stale_launcher?: boolean;
  health?: ClientHealth;
  connected?: boolean;
  details?: string;
}

export interface ClientsPayload {
  results: ClientIntegration[];
}

export interface MemoryListPayload {
  items: MemoryRecord[];
  warning?: string;
}

export interface HealthPayload {
  ok?: boolean;
  provider?: string;
  [key: string]: unknown;
}

export interface OperationMetric {
  name: string;
  count: number;
  errors: number;
  p50_ms?: number;
  p95_ms?: number;
  last_error?: string;
}

export interface OperationMetricsPayload {
  operations?: Record<string, OperationMetric> | OperationMetric[];
  [key: string]: unknown;
}
