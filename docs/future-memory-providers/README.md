# Future Memory Providers

This folder documents how AgentMemory should integrate future memory systems such as:

- Zep
- Hindsight
- memsearch
- A-MEM
- Cognee
- Graphiti
- and other memory-capable tools

The goal is not just to list possible integrations. The goal is to make future provider work understandable, consistent, and aligned with the actual AgentMemory architecture.

## Why This Document Exists

AgentMemory is not meant to be "a wrapper around mem0".

It is intended to become:

- a stable memory runtime contract
- exposed through MCP, CLI, HTTP API, and local tooling
- backed by multiple memory providers
- with provider-specific complexity contained behind adapters

As more memory tools are considered, the project needs a clear answer to these questions:

- what counts as a good provider fit
- what counts as an experimental fit
- how different memory systems map to the AgentMemory contract
- what should live in the provider
- what should live in shared runtime layers

This document is the conceptual and technical guide for that work.

## The AgentMemory Architecture In One View

AgentMemory should be thought of in layers.

### Top Layer: User-facing surfaces

- MCP
- CLI
- HTTP API
- interactive shell
- future editor or client integrations

These surfaces should speak one stable contract.

### Middle Layer: AgentMemory contract

Current core operations:

- `add`
- `search`
- `search_page`
- `list`
- `list_page`
- `get`
- `update`
- `delete`
- `list_scopes`

This is the stable behavioral interface that the rest of the system should trust.

### Bottom Layer: Providers

Providers implement backend-specific behavior:

- data storage
- search
- scope semantics
- update/delete behavior
- transport constraints
- fallback and hydration
- diagnostics

The provider is an adapter layer, not a thin wrapper.

## The Core Design Rule

Upstream tools are not the AgentMemory contract.

That means:

- if a backend returns strange payloads, the provider normalizes them
- if a backend lacks some capability, the provider declares that honestly
- if a backend has locking or transport constraints, the provider surfaces those as runtime policy
- if a backend cannot support a feature reliably, AgentMemory should not fake support

This is what lets AgentMemory present a clean, stable interface while integrating unstable or incomplete systems.

## Not All Memory Systems Are The Same

Future memory systems do not all fit one shape.

AgentMemory should explicitly recognize different provider types.

## Provider Type 1: Record Providers

These are the cleanest fit.

Typical behavior:

- store memory records
- search records
- return stable ids
- sometimes support update/delete
- typically use user/session/scope identifiers

Examples:

- `mem0`
- `Hindsight`
- parts of `Zep`
- future `Qdrant-native`
- future `Chroma`

These are the best targets for the standard AgentMemory contract.

## Provider Type 2: Graph Providers

These systems are often not built around a simple "memory record" abstraction.

Typical behavior:

- build knowledge graphs
- extract entities and relationships
- support graph traversal or temporal reasoning
- may not have simple update/delete semantics at the same granularity as AgentMemory

Examples:

- `Graphiti`
- `Cognee`
- some future graph-memory stacks

These can still be integrated, but they usually require one of these strategies:

- partial contract support
- graph-aware provider implementation
- hybrid storage design

## Provider Type 3: Hybrid Providers

These expose both record-like and graph-like behavior.

Typical behavior:

- searchable memory records
- higher-level semantic or graph structure
- multiple retrieval modes

Examples:

- `Zep`
- some versions of `A-MEM`

These are often strong candidates, but need careful capability declaration.

## Provider Type 4: Companion Tools

Some systems are not best integrated as the primary AgentMemory provider.

They may be:

- plugins
- markdown-based memory tools
- ingestion helpers
- secondary indexing systems

Examples:

- `memsearch` may fall into this category depending on which part of its ecosystem is being integrated

These can still matter a lot, but they may fit better as:

- a lightweight provider
- an import/export integration
- a parallel memory layer

## How Future Providers Should Be Evaluated

Every future memory source should be evaluated against the same questions.

## 1. What is the backend's native unit of memory

Questions:

- does it store records
- does it store graph nodes/edges
- does it store documents
- does it store conversations
- does it store embeddings only

Why it matters:

The closer the native unit is to an AgentMemory `MemoryRecord`, the easier the integration.

## 2. Does it expose stable ids

Questions:

- can records be fetched by id
- do ids survive restarts
- can update/delete operate on those ids

Why it matters:

Without stable ids, `get`, `update`, and `delete` become unreliable or expensive.

## 3. What are its scope semantics

Questions:

- does it support `user_id`
- does it support `agent_id`
- does it support session/thread/run semantics
- does it require scope for reads and writes
- can it enumerate scopes

Why it matters:

Scope handling is central to AgentMemory and should not be guessed in shared layers.

## 4. What kind of search does it actually support

Questions:

- semantic search
- lexical search
- graph traversal
- hybrid ranking
- rerank support

Why it matters:

This drives capability declaration and user guidance.

## 5. What are its write semantics

Questions:

- synchronous write
- eventual consistency
- ingestion pipeline
- asynchronous jobs
- deduplication or merge behavior

Why it matters:

AgentMemory must know whether `add` means:

- immediately materialized
- accepted for processing
- merged into an existing object

## 6. What are its operational constraints

Questions:

- can multiple local clients access it directly
- does it have file locks
- does it require a server process
- does it require a local owner process
- does it require network auth

Why it matters:

This should drive transport policy, not shared-layer provider-name branching.

## Mapping A Future Tool To The AgentMemory Contract

The provider should answer these questions explicitly.

## Required contract questions

- How does `add_memory` work
- How does `search_memory` work
- How does `search_memory_page` work
- How does `list_memories` work
- How does `list_memories_page` work
- Does `get_memory` exist natively
- Does `update_memory` exist natively
- Does `delete_memory` exist natively
- How does `list_scopes` work

If a method cannot be supported cleanly:

- capability should say so
- or the provider should be classified as experimental

## Example capability mapping

A provider should declare things like:

- `supports_semantic_search`
- `supports_text_search`
- `supports_filters`
- `supports_metadata_filters`
- `supports_rerank`
- `supports_update`
- `supports_delete`
- `supports_scopeless_list`
- `requires_scope_for_list`
- `requires_scope_for_search`
- `supports_owner_process_mode`
- `supports_scope_inventory`
- `supports_pagination`

Future runtime policy should also be explicit.

Recommended direction:

- `preferred_transport_mode = "direct" | "owner_process_proxy" | "remote_only"`

This avoids shared-layer logic like `if provider == "mem0"`.

## What Should Live In The Provider

Provider responsibilities:

- upstream API/storage interaction
- payload normalization
- typed error mapping
- capability declaration
- scope behavior
- fallback hydration
- concurrency and transport constraints
- diagnostics

Shared runtime responsibilities:

- one stable contract
- user-facing transports
- capability-aware request validation
- consistent error formatting
- future shared metadata systems such as scope registry
- provider-neutral cursor walking for large list/search/export flows

## What Should Not Live In Shared Layers

Avoid:

- `if provider_name == "..."`
- provider-specific response parsing
- provider-specific error text inspection
- provider-specific transport logic

If a shared layer needs provider-specific branches, the provider contract is probably missing a declared capability or policy.

## Recommended Integration Pattern

When integrating a future provider, use this sequence.

### Step 1: Classify the provider

Choose one:

- record provider
- graph provider
- hybrid provider
- companion tool

This avoids pretending that every backend fits identical semantics.

### Step 2: Define the truth model

Decide what AgentMemory will treat as canonical.

Examples:

- one memory row
- one graph-derived memory summary
- one upstream memory object

Do not start coding before this is clear.

### Step 3: Decide which contract methods are truly supported

Be honest.

Examples:

- `search` supported
- `add` supported
- `update` unsupported
- `delete` unsupported
- `list_scopes` available only through shared scope registry

### Step 4: Implement the provider adapter

The provider should:

- adapt inputs
- call upstream
- normalize outputs
- map errors
- declare capabilities

### Step 5: Decide scope strategy

There are three acceptable approaches.

#### Native scope inventory

Use provider-native scope discovery if the backend supports it cleanly.

#### AgentMemory-owned scope registry

Use a shared AgentMemory metadata/index layer to track scopes independently of backend internals.

This is the recommended long-term pattern.

#### Explicitly unsupported

If the backend cannot support scope inventory reliably and there is no shared registry yet:

- declare `supports_scope_inventory = False`
- raise a typed capability error

This is better than pretending.

### Step 6: Decide transport policy

Decide whether the provider should be:

- direct local
- owner-process proxied
- remote-only

This must be declared as provider/runtime policy, not hard-coded in shared layers.

### Step 7: Add tests before calling it integrated

At minimum:

- contract tests
- capability tests
- scope behavior tests
- transport policy tests
- provider-specific normalization tests
- lifecycle tests for add/get/update/delete where supported

## Examples: How Specific Tools Likely Fit

These are architectural expectations, not final implementation commitments.

## Zep

Likely type:

- hybrid provider

Why it is promising:

- has a real memory API
- already thinks in terms of persistent memory
- likely closer to a clean provider model than many research systems

What to watch:

- graph or enriched memory semantics may be wider than a simple `MemoryRecord`
- decide whether AgentMemory treats Zep as a record provider with enrichment, or as a hybrid provider

Likely maturity path:

- supported provider candidate

## Hindsight

Likely type:

- record provider

Why it is promising:

- service-like memory model
- more likely to align with CRUD-ish runtime semantics

What to watch:

- exact update/delete behavior
- scope semantics
- operational model

Likely maturity path:

- good near-term provider candidate

## memsearch

Likely type:

- companion tool or lightweight provider

Why it is interesting:

- markdown-first memory system
- practical tooling around agent workflows

What to watch:

- may fit better as import/export or lightweight provider than as the canonical production backend
- check how stable ids and update/delete are modeled

Likely maturity path:

- experimental or lightweight provider candidate

## A-MEM

Likely type:

- experimental hybrid or research provider

Why it is interesting:

- memory-system semantics
- research-oriented architecture

What to watch:

- not every research memory system has a clean production-grade CRUD API
- may require interpretation rather than straightforward adapter work

Likely maturity path:

- experimental provider first

## Cognee

Likely type:

- graph provider

Why it is interesting:

- knowledge-engine style architecture
- ingestion plus reasoning layers

What to watch:

- may not map naturally to `get/update/delete` at record granularity
- likely better as graph-oriented integration than a fake record provider

Likely maturity path:

- experimental graph provider

## Graphiti

Likely type:

- graph provider

Why it is interesting:

- temporal graph orientation
- potentially powerful for advanced memory reasoning

What to watch:

- graph lifecycle may not match simple memory-record lifecycle
- best handled with explicit graph-provider semantics

Likely maturity path:

- experimental graph provider

## The Role Of `localjson`

`localjson` should remain the clean reference provider.

Why:

- fully controlled behavior
- no external dependencies
- easy contract testing
- useful as baseline semantics

Every future provider should be compared against `localjson` to determine:

- what behavior is universal
- what behavior is backend-specific
- what behavior is only aspirational

## The Role Of `mem0`

`mem0` is important, but it should not define the architecture.

What it should represent:

- a real semantic memory provider
- a supported but operationally opinionated integration

What it should not become:

- the hidden template that shapes all shared runtime behavior

This matters because future providers should be able to fit without creating new mem0-style shared-layer exceptions.

## Future Shared Systems AgentMemory Likely Needs

As provider count grows, some functionality should move out of provider-specific hacks and into explicit shared systems.

## Shared scope registry

Purpose:

- stable `list_scopes`
- provider-independent scope discovery
- no provider-internal scraping

## Shared pagination contract

Purpose:

- stable `list_page` / `search_page` payloads across providers
- provider-owned opaque cursors instead of shared-layer backend scraping
- large provider-neutral export without silent truncation when a provider implements `list_memories_page`

Future providers such as MemPalace, Hindsight, Memvid-style stores, or
Memweave-style systems should only declare `supports_pagination = True` after
they can resume a record walk without duplicating or skipping records under the
provider's expected consistency model. Providers may still ship without cursor
support by inheriting the base single-page fallback.

## Explicit transport policy

Purpose:

- direct vs proxied vs remote behavior
- no provider-name branching

## Provider maturity model

Purpose:

- reference vs supported vs experimental classification
- clear user expectations

## Provider certification

Purpose:

- consistent contract validation
- public confidence in what "supported" means

## Anti-patterns To Avoid

Do not do these:

- assume every memory system is a record store
- hide unsupported capabilities behind partial hacks
- read provider-private storage formats unless clearly marked experimental
- put provider-name checks in shared transport or API layers
- overstate readiness in docs before capability and operational semantics are stable

## Strong Recommended Direction

As new memory systems are added, AgentMemory should evolve toward this stance:

- shared layers remain provider-neutral
- providers declare capabilities and transport policy explicitly
- scope discovery is eventually owned by AgentMemory or provided natively by backends
- graph systems are integrated honestly as graph or hybrid providers, not forced into fake CRUD semantics

## Practical Reading Order For Future Work

When planning a new provider, read in this order:

1. [PROVIDER_ADAPTER_RULES.md](/O:/user%20files/Projects/tools/AgentMemory/docs/PROVIDER_ADAPTER_RULES.md)
2. [PRELAUNCH_RISKS.md](/O:/user%20files/Projects/tools/AgentMemory/docs/PRELAUNCH_RISKS.md)
3. [PRELAUNCH_REMEDIATION.md](/O:/user%20files/Projects/tools/AgentMemory/docs/PRELAUNCH_REMEDIATION.md)
4. [PROVIDER_INTEGRATION_CHECKLIST.md](/O:/user%20files/Projects/tools/AgentMemory/docs/future-memory-providers/PROVIDER_INTEGRATION_CHECKLIST.md)

Then decide:

- provider type
- contract support level
- scope strategy
- transport policy
- maturity classification
