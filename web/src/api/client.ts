import type {
  ClientsPayload,
  HealthPayload,
  MemoryListPayload,
  MemoryRecord,
  OperationMetricsPayload,
  Scope,
  ScopesPayload,
  StatsPayload,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public payload?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
}

// ── Client-side bearer token (production) ─────────────────────
//
// In dev the Vite proxy injects Authorization from AGENTMEMORY_API_TOKEN
// in process.env, so the SPA doesn't need its own token and we skip the
// prompt to keep HMR dev ergonomic. In prod the SPA talks to Traefik
// directly and has to present the bearer itself — stored in localStorage
// after a one-time window.prompt(). On 401 we clear it and re-prompt.

const TOKEN_KEY = "agentmemory.token";
const USE_CLIENT_TOKEN = !import.meta.env.DEV;

export function getStoredToken(): string {
  if (typeof localStorage === "undefined") return "";
  return localStorage.getItem(TOKEN_KEY) ?? "";
}

export function setStoredToken(value: string): void {
  if (typeof localStorage === "undefined") return;
  if (value) localStorage.setItem(TOKEN_KEY, value);
  else localStorage.removeItem(TOKEN_KEY);
}

export function clearStoredToken(): void {
  setStoredToken("");
}

export const isTokenManaged = USE_CLIENT_TOKEN;

function promptForToken(reason: string): string {
  // window.prompt is synchronous — good enough as a "simplest alert".
  const input = window.prompt(
    `${reason}\n\nPaste AGENTMEMORY_API_TOKEN (bearer):`,
    "",
  );
  if (input === null) {
    throw new ApiError("Authentication cancelled.", 401, null);
  }
  const trimmed = input.trim();
  if (!trimmed) {
    throw new ApiError("Empty token.", 401, null);
  }
  setStoredToken(trimmed);
  return trimmed;
}

function ensureToken(): string {
  const existing = getStoredToken();
  if (existing) return existing;
  return promptForToken("AgentMemory needs an access token to continue.");
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, query, headers, ...rest } = options;

  let url = path;
  if (query) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === "") continue;
      params.set(key, String(value));
    }
    const qs = params.toString();
    if (qs) url += `?${qs}`;
  }

  function buildHeaders(token: string | null): Record<string, string> {
    const out: Record<string, string> = {
      Accept: "application/json",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...((headers as Record<string, string> | undefined) ?? {}),
    };
    if (token) out.Authorization = `Bearer ${token}`;
    return out;
  }

  const doFetch = (token: string | null) =>
    fetch(url, {
      ...rest,
      headers: buildHeaders(token),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });

  let token = USE_CLIENT_TOKEN ? ensureToken() : null;
  let response = await doFetch(token);

  if (USE_CLIENT_TOKEN && response.status === 401) {
    clearStoredToken();
    token = promptForToken(
      "Access denied. The stored token was rejected — paste a fresh one.",
    );
    response = await doFetch(token);
  }

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!response.ok) {
    const message =
      (payload as { error?: string } | null)?.error ??
      (typeof payload === "string" ? payload : null) ??
      `Request failed: ${response.status}`;
    throw new ApiError(message, response.status, payload);
  }

  return payload as T;
}

export interface MemoryListQuery extends Scope {
  query?: string;
  pinned?: boolean;
  limit?: number;
}

export const api = {
  health: () => request<HealthPayload>("/health"),

  stats: () => request<StatsPayload>("/admin/stats"),
  operations: () => request<OperationMetricsPayload>("/admin/stats/operations"),
  clients: () => request<ClientsPayload>("/admin/clients"),
  scopes: () => request<ScopesPayload>("/admin/scopes"),

  listMemories: (query: MemoryListQuery = {}) =>
    request<MemoryListPayload>("/admin/memories", {
      query: {
        query: query.query,
        user_id: query.user_id,
        agent_id: query.agent_id,
        run_id: query.run_id,
        pinned: query.pinned ? "true" : undefined,
        limit: query.limit ?? 200,
      },
    }),

  getMemory: (id: string) =>
    request<MemoryRecord>(`/admin/memories/${encodeURIComponent(id)}`),

  updateMemory: (
    id: string,
    patch: {
      memory?: string;
      metadata?: Record<string, unknown>;
      pinned?: boolean;
      archived?: boolean;
    },
  ) =>
    request<MemoryRecord>(`/admin/memories/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: patch,
    }),

  deleteMemory: (id: string) =>
    request<{ ok?: boolean }>(`/admin/memories/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),

  pinMemory: (id: string, pinned: boolean) =>
    request<MemoryRecord>(`/admin/memories/${encodeURIComponent(id)}/pin`, {
      method: "POST",
      body: { pinned },
    }),

  addMemory: (payload: {
    text?: string;
    messages?: Array<{ role: string; content: string }>;
    user_id?: string;
    agent_id?: string;
    run_id?: string;
    metadata?: Record<string, unknown>;
    infer?: boolean;
    dedup?: boolean;
  }) =>
    request<MemoryRecord | { items?: MemoryRecord[] }>("/add", {
      method: "POST",
      body: payload,
    }),
};
