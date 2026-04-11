# Prelaunch Remediation

This document describes how to resolve the main prelaunch risks in AgentMemory without losing the core architecture.

## Goal

Preserve the existing model:

- shared AgentMemory contract
- provider adapters
- MCP/CLI/HTTP transports

while removing the parts that are still too provider-specific, operationally unsafe, or too fragile for strong public claims.

## Problem 1: `mem0` scope inventory relies on backend internals

### Target state

`list_scopes` should be powered by an AgentMemory-owned scope registry or by a native provider capability, not by reverse-engineering provider storage.

### Recommended solution

Introduce an internal `scope_registry` owned by AgentMemory.

Suggested fields:

- `provider`
- `kind`
- `value`
- `count`
- `last_seen_at`

Optional fields:

- `first_seen_at`
- `source_record_id`
- `is_deleted` or tombstone markers if needed later

### How it should work

On every memory write path:

- `add`
- `update`
- `delete` when relevant

the provider adapter or shared runtime updates the scope registry for any known:

- `user_id`
- `agent_id`
- `run_id`

Then `list_scopes` reads from this registry instead of provider internals.

### Why this is better

- provider-independent
- stable across backend upgrades
- no parsing of unsupported storage formats
- no dependency on `pickle`
- works even for providers that do not support global scope discovery

### Transitional plan

Phase 1:

- keep current `mem0` implementation but mark it `experimental`

Phase 2:

- add AgentMemory-owned scope registry
- make `list_scopes` read from it first

Phase 3:

- remove or downgrade the qdrant/sqlite fallback path

### Provider policy after remediation

For each provider:

- if provider has native scope inventory, adapter may use it
- otherwise provider can rely on the shared scope registry
- if neither is available, `supports_scope_inventory = False`

This keeps the contract honest.

## Problem 2: HTTP API is unsafe if exposed outside localhost

### Target state

The security model must be explicit and enforced:

- either localhost-only by default and difficult to expose accidentally
- or authenticated when exposed on the network

### Recommended short-term solution

Make localhost-only the enforced default.

Concrete changes:

- default bind host remains `127.0.0.1`
- refuse non-local bind unless the user passes an explicit unsafe flag
- print a strong warning when unsafe bind is enabled

Suggested flag:

- `--allow-unsafe-network-bind`

### Recommended long-term solution

Add token-based authentication.

Simple model:

- generate or configure an API token
- require `Authorization: Bearer <token>` on admin and write endpoints
- optionally allow read-only unauthenticated localhost paths if desired, but only intentionally

### Why this is better

- prevents accidental remote exposure
- supports a future hosted/server narrative safely
- gives docs a clear security model

## Problem 3: proxy logic is still tied to the provider name `mem0`

### Target state

Transport behavior should depend on provider capabilities or runtime policy, not provider identity.

### Recommended solution

Replace provider-name branching with explicit runtime semantics.

Suggested capability or policy fields:

- `supports_owner_process_mode`
- `requires_owner_process_proxy`
- `preferred_transport_mode`

Example policy values:

- `direct`
- `owner_process_proxy`
- `remote_only`

### How it should work

The provider declares operational constraints.

The transport layer decides:

- direct local call
- local API proxy call
- future remote provider call

based on declared policy.

### Why this is better

- truly provider-neutral transport
- easier onboarding of future providers
- avoids shared-layer `if provider == ...` growth

## Problem 4: public claims can exceed actual guarantees

### Target state

Public messaging should match current technical guarantees exactly.

### Recommended solution

Split readiness into explicit categories in docs.

Suggested categories:

- `Reference providers`
- `Supported providers`
- `Experimental providers`
- `Operational limitations`

### Suggested current classification

- `localjson`: reference provider
- `mem0`: supported but operationally constrained
- future `Qdrant-native`: target for a cleaner production-style provider

### Documentation to add or strengthen

- security model
- provider maturity matrix
- known limitations
- deployment modes
- when MCP/API restart is required after upgrades

## Concrete Prelaunch Checklist

### Blockers before strong public claims

- move scope inventory off provider internals or mark it clearly experimental
- enforce localhost-only API or add auth
- remove provider-name-specific proxy policy from shared transport logic

### Should fix before broader community promotion

- add a provider maturity matrix to README
- document security assumptions explicitly
- document restart behavior for local API and MCP clients

### Nice to have

- implement `Qdrant-native` as a cleaner provider
- add token auth for networked API mode
- add provider certification output to public docs

## Suggested Messaging After Remediation

Once the blockers are handled, a much stronger public claim becomes defensible:

- AgentMemory provides a stable shared contract across transports and providers.
- Providers can implement memory storage and retrieval while AgentMemory owns the operational contract.
- Scope discovery, transport policy, and security are handled intentionally rather than by provider-specific behavior.

