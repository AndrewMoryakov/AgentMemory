# Prelaunch Remediation

This document maps the original prelaunch remediation plan to the current code
state and lists the remaining remediation work before stronger production-style
claims are defensible.

The active issue tracker for concrete tasks is [BACKLOG.md](BACKLOG.md).

## Remediation Status

| Original problem | Current status | Notes |
|---|---|---|
| `mem0` scope inventory relies on backend internals | resolved | Runtime `list_scopes` reads the AgentMemory-owned SQLite scope registry. Qdrant/pickle access remains only as an explicit legacy rebuild seed path. |
| HTTP API unsafe if exposed outside localhost | mostly resolved | Protected paths support bearer/OAuth auth, root Docker Compose requires `AGENTMEMORY_API_TOKEN`, and the default published bind is loopback. Hosted/multi-user auth is still out of scope. |
| Proxy logic tied to provider name | resolved | Routing uses provider runtime policy such as `direct` and `owner_process_proxy`. |
| Public claims can exceed guarantees | partially resolved | README now links current limitations. Scope-registry scalability and degraded-registry recovery expectations still limit production-style claims. |

## Remaining Remediation Work

## 1. Make the TTL sweeper exhaustive

### Target state

The hard-delete sweeper should discover every registry-known expired record
without depending on first-page provider windows.

### Current status

Implemented for registry-backed providers. Scope registry rows include
`metadata.expires_at`, and the sweeper reads expired ids from that index before
deleting from the primary provider store. The older scope/memory walk remains as
a compatibility fallback when no registry expired-id helper is injected.

Tracked in [BACKLOG.md](BACKLOG.md) as a closed `P1` item.

## 2. `list_scopes` cursor pagination

### Target state

Scope inventory should support the same provider-neutral page pattern as memory
records:

- `provider`
- `items`
- `next_cursor`
- `pagination_supported`
- `totals`

The old `list_scopes` shape should remain the backwards-compatible first-page
API.

### Current status

Implemented. `list_scopes_page` now exposes the page shape above, preserves
current ordering/filtering/totals, and provider-neutral export walks scope
pages. TTL sweeper discovery now uses the registry TTL index instead of scope
window traversal.

Tracked in [BACKLOG.md](BACKLOG.md) as a closed `P1` item.

## 3. Improve scope registry scaling

### Target state

Small inventory calls should not require loading and aggregating every registry
row in Python.

### Recommended implementation

- Move aggregation/filtering into SQL where possible.
- Add indexes for provider/scope fields if the current schema does not already
  cover the hot path.
- Keep totals accurate without making small page reads scan unnecessary data.

Tracked in [BACKLOG.md](BACKLOG.md) as a `P2` item.

## 4. Align admin memory views with TTL policy

### Target state

Admin memory list/stats should either match normal lifecycle filtering or be
explicitly documented as raw-provider inspection.

### Current status

Implemented. Admin list/search results, admin stats, and direct admin-get now
hide expired records using the shared lifecycle TTL predicate.

Tracked in [BACKLOG.md](BACKLOG.md) as a closed `P2` item.

## 5. Keep public docs aligned with implementation state

### Target state

Public entry points should say three things clearly:

- what is implemented and safe to try
- what is supported but operationally constrained
- what is known and still open

### Current policy

- [README.md](../README.md) contains a `Current Limitations` section.
- [START_HERE.md](START_HERE.md) points evaluators to the backlog.
- This document and [PRELAUNCH_RISKS.md](PRELAUNCH_RISKS.md) should be treated
  as current status documents, not frozen historical notes.

## Suggested Messaging

The project can make stronger claims if messaging stays inside runtime scope:

- AgentMemory provides a stable shared contract across transports and providers.
- Providers can implement memory storage and retrieval while AgentMemory owns
  the operational contract.
- Scope discovery, transport policy, security defaults, lifecycle filtering,
  and portability are handled intentionally rather than by provider-specific
  behavior.
- TTL should be described as optional caller-controlled lifecycle support, not
  as automatic short-term/long-term memory management by the runtime.

Keep the public framing at `public alpha` and link to the backlog for current
limitations.

## 6. Improve scope registry scaling

### Target state

Small scope-inventory calls should not require materializing every provider row
in Python before `limit` is applied.

### Current status

Implemented. Scope inventory aggregation, sorting, totals, and page limiting now
run inside SQLite, preserving the existing response shape and ordering while
avoiding Python full-table grouping on the hot path.

Tracked in [BACKLOG.md](BACKLOG.md) as a closed `P2` item.
