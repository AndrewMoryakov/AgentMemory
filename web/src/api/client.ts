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

  const response = await fetch(url, {
    ...rest,
    headers: {
      Accept: "application/json",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(headers ?? {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

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
