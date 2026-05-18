# Prelaunch Risks

This document records the current public-alpha risks for AgentMemory.

Historical note: earlier versions of this file listed several launch blockers
that are now resolved in code: auth on protected HTTP paths, provider-neutral
scope inventory, runtime-policy based proxy routing, and safer root Docker
Compose defaults. The active source of truth for specific bugs and follow-ups is
[BACKLOG.md](BACKLOG.md).

## Current Risk Summary

AgentMemory is now a stronger local shared-memory runtime than the original
prelaunch assessment described, but it is still a public alpha. The remaining
risks are mostly conservative `mem0` record pagination, degraded-registry
recovery expectations, and public-claim accuracy.

## Risk 1: Registry-backed TTL sweeps depend on registry health

### What is happening

The TTL sweeper no longer walks fixed-size scope and record windows. It uses the
scope registry's `expires_at` index to discover expired memory ids. If registry
sync is degraded, `doctor` reports that a rebuild is needed.

### Why this matters

The primary provider store remains the source of truth. A degraded or stale
registry can make hard-delete discovery incomplete until
`agentmemory rebuild-scope-registry` is run.

### Tracking

Tracked through scope-registry diagnostics and rebuild guidance.

## Risk 2: `mem0` pagination is intentionally conservative

### What is happening

`localjson` implements real cursor pagination. `mem0` currently advertises
`supports_pagination = False` and uses the base single-page fallback.

### Why this matters

This is honest and safe, but it means large mem0 walks still need a backend-safe
cursor strategy before they can match the `localjson` pagination behavior.

### Tracking

## Risk 3: Operational network drift is mitigated, not root-fixed

### What is happening

Docker Compose v2 external-network drift has been observed on the deployment
host. `deploy/redeploy.sh` reattaches the container idempotently, so the symptom
is mitigated for AgentMemory deployments. The repo now also carries an
issue-ready reproducer and upstream report draft in
[COMPOSE_V2_NETWORK_DRIFT.md](COMPOSE_V2_NETWORK_DRIFT.md).

### Why this matters

The root cause is upstream/outside this repo. Similar future services could hit
the same drift if they do not use the guarded redeploy path.

### Tracking

Tracked as locally guarded and upstream-documented in
[BACKLOG.md](BACKLOG.md): Compose v2 network drift.

## Resolved Prelaunch Risks

The following original prelaunch risks are no longer active blockers:

- `mem0` runtime scope inventory no longer reads Qdrant private storage or
  `pickle` blobs. Normal `list_scopes` reads the AgentMemory-owned SQLite scope
  registry. The legacy reader remains only for explicit one-shot rebuild.
- Protected HTTP/MCP/admin paths require bearer/OAuth auth when auth is
  configured, and the root Docker Compose requires `AGENTMEMORY_API_TOKEN`.
- Internal owner-process proxy calls propagate bearer auth.
- Transport routing is driven by provider runtime policy, not shared-layer
  `if provider == "mem0"` branching.
- `localjson` uses cross-process file locking and atomic replace for direct
  local transport.
- Request body size is capped, and authenticated requests are rate-limited.
- Normal list/search reads, page list/search reads, and provider-neutral export
  filter TTL-expired records from user-facing payloads.
- Scope inventory exposes `list_scopes_page`, and provider-neutral export walks
  scope pages instead of using a fixed scope guard.
- Future-provider contract hardening now allows unsupported update/delete when
  declared honestly, and runtime registry, certification metadata, policy, and
  onboarding share provider descriptors.

## Public Messaging Guidance

Safe framing now:

- AgentMemory is a public-alpha shared local memory runtime.
- The local runtime, provider contract, MCP/HTTP/CLI surfaces, scope registry,
  and provider certification path are real and test-covered.
- `localjson` is the clean reference provider.
- `mem0` is supported but operationally constrained and still conservative on
  cursor pagination.
- Known limitations are tracked openly in [BACKLOG.md](BACKLOG.md).

Avoid framing until the remaining P1 lifecycle/pagination items are closed:

- "production-ready universal memory server"
- "complete retention/hard-delete guarantee for arbitrarily large stores"
- "fully paginated provider-neutral export for every provider"
- "secure multi-user hosted memory service"
