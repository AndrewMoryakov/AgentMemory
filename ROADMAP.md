# AgentMemory Roadmap

This document tracks the next major product directions for AgentMemory.

It now reflects the current state of the core runtime, not only the UI direction.

## Current Product Shape

AgentMemory already provides:

- a provider-based shared-memory runtime
- a local HTTP API
- a local MCP server
- install, configure, and diagnostics CLI workflows
- Windows-first client auto-connect
- a production `mem0` provider
- a simple built-in `localjson` provider
- `Provider Contract V1`
- shared transport validation and error shaping
- shared core operation registry for CLI, HTTP API, and MCP
- shared transport input adapters for CLI, HTTP API, and MCP
- provider certification helpers, registry, and CI checks
- capability-aware diagnostics and client/runtime guidance

This means the project is no longer only a wrapper around a provider. It now has a real local runtime architecture.

## Core Runtime Status

The core memory operations now have a mostly unified architecture:

- one typed provider contract
- one shared operation registry
- one shared runtime/proxy execution layer
- one shared transport validation layer
- one shared adapter model for CLI, HTTP API, and MCP inputs

This closes the biggest architecture gap from the earlier alpha state.

The next major work is no longer basic standardization. It is productization and surface expansion on top of that baseline.

## Provider Architecture Readiness

The current architecture is directionally ready for more providers.

It is already strong enough to support additional local and self-hosted backends such as:

- `Qdrant-native`
- `Chroma`
- `LanceDB`
- `pgvector`

It is also close to ready for heavier or more operationally complex backends such as:

- `Weaviate`
- `Milvus`
- hosted API-based memory services

What is already working well:

- provider abstraction is separated from transport layers
- one shared operation registry already exists
- MCP, HTTP API, and CLI already share the same execution path
- capability flags already exist
- provider certification and contract harnesses already exist
- owner-process and proxy execution patterns already exist for backends with runtime constraints

What still needs to be hardened before the project can scale cleanly to many providers:

- provider result semantics need to be more explicit
- partial success and no-op success responses need stronger certification coverage
- provider development rules need to stay explicit and enforced
- provider diagnostics need to be consistent across local, remote, and hosted backends
- backend-specific quirks must remain contained inside provider adapters

The current architecture should not be rewritten.

The next step is to make the provider boundary stricter and more explicit, not to replace the overall runtime design.

## Provider Ecosystem Readiness Work

Before broad provider expansion, the roadmap should include a short hardening pass focused on provider integration quality.

### 1. Formalize Provider Result Semantics

Define stable meanings for operation outcomes such as:

- materialized success
- accepted but not yet materialized
- no-op success
- partial success
- canonical delete success

Why this matters:

- some backends return rich records
- some return message-only success payloads
- some return wrappers such as `results`
- some may become eventually consistent or async

The provider layer must normalize those cases without leaking backend ambiguity into MCP, CLI, or HTTP.

### 2. Strengthen Provider Certification

Extend certification and contract tests for:

- empty result wrappers on success
- message-only success payloads
- partial record payloads
- hydration and fallback lookup behavior
- no-op add, update, and delete behavior
- hosted and eventually consistent backend patterns later

Why this matters:

- one provider contract is only real if backend edge cases are tested consistently

### 3. Keep Provider Rules Explicit

Treat provider modules as adapter layers, not thin SDK wrappers.

The document [PROVIDER_ADAPTER_RULES.md](docs/PROVIDER_ADAPTER_RULES.md) should remain part of the architectural baseline for all future providers.

Why this matters:

- upstream SDKs and APIs are not stable contracts
- transport and API layers must stay backend-agnostic
- backend quirks must terminate at the provider boundary

### 4. Add One Clean Reference Provider

Add one provider with a simpler and more explicit backend contract, preferably:

- `Qdrant-native`

Good follow-up candidates:

- `Chroma`
- `pgvector`
- `LanceDB`

Why this matters:

- it will show whether the current architecture is truly provider-generic
- it reduces the risk of accidental `mem0`-shaped assumptions staying in the runtime

### 5. Normalize Operational Guidance Across Providers

Expand provider-aware diagnostics so they can consistently describe:

- scope requirements
- concurrency constraints
- owner-process requirements
- hosted API limits
- missing credentials
- degraded or partial runtime states

Why this matters:

- a universal memory runtime needs operator-facing clarity, not just provider code paths

## Near-Term Direction

Near-term product work should prioritize:

1. capability-aware lifecycle and client UX
2. admin surface cleanup and operational consistency
3. packaging, install, and cross-platform workflow quality
4. memory console improvements on top of the now-stable runtime core

## Product Direction: Memory Console

AgentMemory needs a high-level management UI, not just raw CLI and JSON access.

The goal is not only to inspect memory records, but to help users:

- understand what is stored
- understand why it exists
- manage memory quality over time
- separate durable facts from noisy ephemeral records
- operate the runtime and provider layer visually

## Why This Matters

Without a management UI, memory systems tend to become opaque and noisy.

A useful memory product needs:

- visibility
- review workflows
- cleanup workflows
- runtime diagnostics
- provider and client visibility

The UI should be a memory console, not just a CRUD browser.

## UI Vision

### 1. Overview

Main dashboard for runtime and operational state.

Should show:

- active provider
- API and MCP health
- connected clients
- total memory count
- recent writes
- warnings and degraded states

Examples of warnings:

- provider not configured
- API not running
- missing credentials
- provider degraded
- runtime lock or backend warnings

### 2. Memory Explorer

Primary working view for browsing and searching stored memory.

Should support:

- full-text or semantic search
- filters by:
  - provider
  - user_id
  - agent_id
  - run_id
  - tags
  - metadata
  - date range
  - memory type
- sorting by:
  - recent
  - updated
  - relevance

Each memory record should expose:

- text or canonical data
- metadata
- timestamps
- provider
- memory id
- score or relevance when applicable
- raw payload toggle

### 3. Memory Review

High-level memory quality workflow.

This is more important than raw editing.

The UI should support actions such as:

- keep
- pin
- archive
- delete
- rewrite
- mark stale
- merge duplicates
- convert to canonical fact

This is how the product avoids turning into a memory junk drawer.

### 4. Runtime and Integrations

System management view for:

- current provider
- current API host and port
- snippets
- MCP status
- client connection state
- Docker deployment information
- runtime logs or recent errors

## MVP Scope

The first UI version should stay narrow and useful.

### Phase 1: Console MVP

Build:

- Overview
- Memory Explorer
- scoped browsing for `mem0` (`user_id`, `agent_id`, `run_id`)
- shareable explorer URLs
- record inspection
- delete
- edit
- pin
- runtime health
- client status

This is enough to make memory visible and manageable.

Status:

- implemented
- current console supports scoped browsing for `mem0`
- current console supports shareable links such as `/ui?user_id=demo-user`
- current console exists on top of a unified core operation layer, which should now remain the baseline for future admin/API work

### Phase 2: Review Workflow

Build:

- recent memories queue
- archive action
- stale action
- tags
- quick review actions directly in cards and detail views
- filters for archived, stale, untagged, and needs-review records
- canonical rewrite flow

Primary goal:

- improve memory quality, not just visibility

Why this phase matters:

- without review workflows, memory becomes a junk drawer
- useful long-term memory needs active cleanup and triage
- agents can keep writing records, but humans need a fast way to curate them

Pass 2 MVP should focus on:

- `archive`
- `mark stale`
- `tags`
- `recent queue`

Expected user-facing actions:

- keep
- pin
- archive
- mark stale
- delete
- tag

Expected outcomes:

- durable facts are separated from temporary noise
- new records can be reviewed shortly after they are added
- the memory store remains useful over time instead of only growing

This phase improves memory quality, not just visibility.

### Phase 3: Explainability and Structure

Build:

- retrieval traces
- source provenance
- timeline view
- entity or graph views
- clusters or grouping
- "why was this retrieved?" visibility

This phase improves trust and debugging.

Why this phase matters:

- users need to understand why memory retrieval happened
- debugging poor retrieval requires visibility into ranking and provenance
- explainability increases trust in the system

Expected outcomes:

- the console can explain why a memory appeared
- users can distinguish strong signal from noise
- retrieval behavior becomes inspectable instead of opaque

### Phase 4: Collaboration and Shared Spaces

Build:

- multiple memory spaces
- user, team, and project scopes
- shared spaces
- basic permissions or role boundaries
- handoff flows between humans and agents
- team review workflows

Why this phase matters:

- memory becomes more useful when it can be shared cleanly
- teams need boundaries between personal, project, and shared memory
- multi-agent workflows benefit from structured shared contexts

Expected outcomes:

- AgentMemory supports both personal and shared use
- teams can organize memory by context instead of one global pool
- human and agent handoff becomes easier to manage

### Phase 5: Provider Ecosystem

Build:

- more production providers
- provider capability model
- provider migration workflows validated against the shared operation layer
- provider-specific settings in the console
- import and export
- provider migration workflows
- comparative diagnostics across providers

Why this phase matters:

- a universal memory runtime becomes much stronger with multiple real backends
- different use cases need different storage and retrieval models
- the product should make providers swappable without changing the user-facing surface

Expected outcomes:

- users can choose a backend that fits their use case
- the runtime becomes a real platform, not just a single-backend wrapper
- migrations between backends become operationally manageable

Current status:

- provider capability model is already implemented at the runtime level
- provider certification workflow is already implemented
- what remains is ecosystem growth and more real providers

### Phase 6: Packaging and Distribution

Build:

- polished Docker workflows
- stronger install and update paths
- first-run setup improvements
- release packaging
- portable distribution improvements
- better docs, examples, and demos
- possibly desktop packaging later

Why this phase matters:

- product value is limited if setup and maintenance remain too manual
- packaging quality determines whether the project can spread beyond a single machine
- smoother onboarding improves community adoption

Expected outcomes:

- easier installation and upgrades
- clearer distribution story for users and contributors
- less friction for trying the product

### Phase 7: Hosted and Team Operations

Build:

- remote deployment patterns
- centralized shared instances
- auth and access control
- auditing
- operational logs
- backup and restore workflows
- remote admin console
- event or webhook integration where useful

Why this phase matters:

- local-first is strong for individuals, but teams may want a managed shared service
- operational controls become essential once the product serves multiple users or environments
- this phase turns the runtime into a serious shared system

Expected outcomes:

- AgentMemory can run as a team service, not only as a personal local tool
- operators can manage reliability, security, and lifecycle concerns
- the product becomes viable for broader shared use

## Backend Work Needed

The current API is operational, and the core memory routes already share the same execution layer as CLI and MCP.

The remaining backend work is mostly about the admin surface, not the core memory routes.

Needed admin-oriented endpoints likely include:

- `GET /admin/stats`
- `GET /admin/memories`
- `GET /admin/memories/{id}`
- `PATCH /admin/memories/{id}`
- `POST /admin/memories/{id}/pin`
- `POST /admin/memories/{id}/archive`
- `POST /admin/memories/{id}/stale`
- `POST /admin/memories/{id}/tags`
- `GET /admin/recent`
- `GET /admin/clients`
- `GET /admin/provider`
- `GET /admin/logs`

These are intentionally separate from the existing operational API surface.

The core operational routes are already unified and should stay aligned across:

- CLI
- HTTP API
- MCP

## Data Model Work

To support a useful UI, AgentMemory will likely need higher-level state beyond provider-native records.

Potential additions:

- review status
- pinned flag
- archived flag
- stale flag
- tags
- reviewed_at
- canonical text
- source provenance
- last retrieved time
- duplicate grouping

Some of this may live above providers instead of inside provider-native storage.

## UX Requirements

The UI should optimize for:

- clarity
- trust
- cleanup
- explainability

The UI should avoid becoming:

- a raw JSON inspector only
- a generic admin panel
- a thin wrapper around existing CLI commands

## Suggested Stack

Pragmatic implementation path:

- keep the current Python backend
- keep the current HTTP API as the base
- add an admin API layer
- build the frontend with React + Vite

Deployment options:

- local desktop-browser workflow
- Docker alongside the existing API

## Product Goals

The UI should make AgentMemory feel like:

- a usable memory product
- a local memory console
- a human-manageable control plane for shared AI memory

Not just:

- a backend
- a Python package
- a collection of scripts

## Near-Term Deliverables

Recommended next implementation order:

1. Expand capability-aware guidance into more client and onboarding flows.
2. Unify admin-oriented operations as cleanly as core memory operations.
3. Improve packaging, install, and cross-platform operational docs.
4. Continue memory console work on top of the stabilized runtime core.
5. Add review queue for newly added records.
6. Add explainability views later.

Longer-term product ladder:

1. Runtime reliability and diagnostics
2. Visibility
3. Review
4. Explainability
5. Collaboration
6. Provider ecosystem
7. Packaging and distribution
8. Hosted and team operations

## Non-Goals For The First UI Version

- full desktop app packaging
- enterprise auth
- multi-tenant remote hosting
- graph visualization from day one
- complex analytics dashboards

The first version should solve visibility and management first.
