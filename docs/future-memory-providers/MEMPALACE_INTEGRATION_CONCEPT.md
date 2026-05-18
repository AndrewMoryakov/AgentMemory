# MemPalace Integration Concept

## Summary

MemPalace is a strong candidate for the next semantic local-first provider, but it should not be integrated as "the whole MemPalace system". It should be integrated as a **hybrid provider with a record-first v1**.

That means:

- use MemPalace as a storage and retrieval backend
- expose one stable AgentMemory `MemoryRecord` contract
- keep MemPalace-specific mining, layers, and graph semantics out of the shared runtime contract

This preserves the AgentMemory architecture:

- `AgentMemory` remains the runtime
- `MemPalace` remains the backend engine
- the provider absorbs the mismatch

## Why MemPalace Is A Good Candidate

MemPalace is attractive because it is not `mem0`-shaped and not file-backed like `claude_memory`.

That makes it useful as an architecture test:

- it checks whether AgentMemory really supports multiple backend styles
- it gives a second local-first semantic backend
- it reduces the chance that the runtime silently drifts into `mem0`-specific assumptions

At the same time, it is more than a simple record store. Public MemPalace material describes:

- layered memory
- semantic recall
- knowledge graph behavior
- mining and compaction flows
- its own MCP-facing tooling

That is exactly why the integration must stay narrow and honest.

## Classification

MemPalace should be treated as a:

- `hybrid provider`

But the AgentMemory v1 integration should use only the subset that can behave like a reliable record provider.

In practice:

- `AgentMemory` sees it as a record-oriented semantic backend
- unsupported higher-level MemPalace semantics stay outside the core provider contract

## Core Rule

Do not integrate "all of MemPalace" into the AgentMemory provider.

The provider should not try to expose:

- mining workflows
- wake-up or layer progression semantics
- graph traversal as ordinary `search`
- MemPalace MCP tools as AgentMemory backend calls

If we do that, AgentMemory stops being a provider-neutral runtime and starts bending around one backend's product model.

## V1 Integration Boundary

The `mempalace` provider should include only:

- `add_memory`
- `search_memory`
- `list_memories`
- `get_memory`
- `delete_memory`
- `update_memory` only if the backend can do it cleanly and predictably
- shared AgentMemory scope-registry integration if scope metadata is stored in records

The provider should not include in v1:

- knowledge graph queries
- layer-aware recall APIs
- compaction or mining jobs as part of ordinary writes
- backend-private storage inspection
- MCP-to-MCP bridging

## Canonical Record Unit

The AgentMemory `MemoryRecord` should map to one MemPalace verbatim memory unit stored in a dedicated AgentMemory-owned collection or namespace.

Recommended mapping:

- `id`: native MemPalace record id
- `memory`: stored verbatim content
- `metadata`: native metadata plus normalized AgentMemory metadata
- `provider`: `mempalace`
- `created_at` / `updated_at`: native timestamps if available, otherwise `None`
- `user_id` / `agent_id` / `run_id`: stored as AgentMemory-managed metadata fields

This keeps the provider contract clean and makes export/import, runtime diagnostics, and search behavior easier to reason about.

## Storage And Namespace Strategy

Use a dedicated AgentMemory-owned MemPalace namespace, collection, or equivalent storage partition.

Why:

- prevents mixing AgentMemory contract records with unrelated MemPalace product data
- allows stable scope metadata conventions
- avoids having runtime behavior depend on MemPalace internal organizational choices
- makes migration and certification easier

The provider should never assume that "all MemPalace memory on disk" belongs to AgentMemory.

## Write Semantics

`add_memory()` should be a direct write of one normalized record into the AgentMemory-owned MemPalace area.

It should not:

- trigger a large mining workflow as a contract requirement
- depend on graph extraction to succeed
- require asynchronous layer-building before the write is visible

If MemPalace performs additional internal indexing after the write, that is acceptable only if the observed write semantics for AgentMemory remain honest and well documented.

The safe default assumption is:

- primary verbatim record write first
- additional MemPalace intelligence is backend-internal and optional from the AgentMemory contract perspective

## Search Semantics

`search_memory()` should use MemPalace's semantic retrieval over the AgentMemory-owned namespace.

V1 should keep this narrow:

- semantic search only
- no graph traversal disguised as ordinary search
- no layer-specific recall modes in the base search path
- no provider-specific query DSL leaking into the runtime

This implies the likely initial capability profile:

- `supports_semantic_search = True`
- `supports_text_search = False`
- `supports_rerank = False` unless the backend really exposes stable rerank behavior

## Scope Strategy

MemPalace does not appear to be built around AgentMemory's `user_id` / `agent_id` / `run_id` model.

So the provider should treat scope as AgentMemory-owned metadata:

- store scope fields in record metadata on write
- apply scope filters through provider-level filtering logic
- maintain AgentMemory shared scope registry on successful add/update/delete if the provider declares scope inventory support

Recommended v1 stance:

- `supports_scope_inventory = True` only if the provider updates the shared scope registry
- `list_scopes()` must read from the AgentMemory registry, not MemPalace internals

This is the same architectural rule already used for other providers.

## Transport Policy

Recommended v1 transport mode:

- `direct`

Reason:

- MemPalace is a local-first backend candidate
- we should not invent owner-process constraints until they are observed in practice

But this must remain a measured choice, not a promise. If real multi-process problems appear later, the provider can move to:

- `owner_process_proxy`

The shared runtime should not need any provider-name branching either way.

## Capability Recommendation For V1

Conservative initial target:

- `supports_semantic_search = True`
- `supports_text_search = False`
- `supports_filters = True` only if backend-side filtering is stable enough to certify
- `supports_metadata_filters = True` only if metadata filter semantics are predictable
- `supports_rerank = False`
- `supports_update = False` unless update is demonstrably reliable
- `supports_delete = True`
- `supports_scopeless_list = True`
- `requires_scope_for_list = False`
- `requires_scope_for_search = False`
- `supports_owner_process_mode = False`
- `supports_scope_inventory = True` if AgentMemory scope registry is maintained
- `supports_pagination = False` in the first pass

Why keep pagination off initially:

- MemPalace must prove stable cursor walk semantics before advertising it
- the runtime should not fake pagination by scraping internals or replaying unstable top-k results

## Recommended Operation Semantics

### add

- direct record write
- return a canonical normalized `MemoryRecord`
- fail closed if the backend cannot return or hydrate a stable id

### search

- semantic retrieval against the AgentMemory-owned namespace
- normalize scores into standard search results
- no MemPalace-specific query shape exposed above the provider

### list

- return normalized records from the AgentMemory-owned namespace
- stable ordering should be documented and tested

### get

- direct lookup by native record id

### update

- only enable if the backend has clean replace semantics at the record level
- otherwise declare unsupported honestly

### delete

- delete by id
- return canonical `DeleteResult`

### list_scopes

- use AgentMemory shared scope registry if supported
- never inspect provider-private storage directly for runtime scope inventory

## What Must Stay Out Of V1

These features are interesting but should remain out of the first provider pass:

- layer-aware query modes
- graph-native APIs
- mined summaries as primary record content
- background compaction semantics in the provider contract
- direct reuse of MemPalace MCP tools as the backend integration boundary

Those can be explored later as:

- experimental provider extensions
- separate runtime operations
- optional admin or observability tooling

But they should not distort the base provider contract.

## Risks

### 1. Product-model leakage

The biggest risk is letting MemPalace's richer product model leak into the shared runtime contract.

That would make future providers harder to integrate and would weaken AgentMemory's provider-neutral architecture.

### 2. Update semantics

Hybrid systems often store more than a simple verbatim record. If record update is not truly clean, `supports_update` should stay off.

### 3. Filtering and scope fidelity

If MemPalace filtering semantics do not line up with AgentMemory expectations, the provider must either normalize carefully or declare narrower support.

### 4. Pagination pressure

There will be temptation to advertise pagination early. That should be resisted until the backend can resume large list walks without duplication or omission under expected consistency conditions.

### 5. Overstated readiness

MemPalace may become a strong provider, but it should likely start as:

- `experimental`

and only move higher after contract tests, runtime diagnostics, and operational behavior are proven.

## Recommended Implementation Sequence

### Phase 1

- create `MemPalaceProvider`
- target dedicated AgentMemory-owned MemPalace namespace
- implement `add/search/list/get/delete`
- leave `update` off unless cleanly supported
- wire shared scope registry if scope metadata is stored
- certify no pagination

### Phase 2

- validate filter semantics
- validate multi-process behavior
- decide whether `direct` remains correct or whether owner-process mode is needed
- harden diagnostics and provider guidance

### Phase 3

- consider optional advanced integration points for graph or layered recall
- only if they can be added without weakening the base provider contract

## Final Position

MemPalace is a strong next provider candidate precisely because it is not a trivial fit.

The right approach is:

- use MemPalace as a backend engine
- keep AgentMemory as the runtime
- integrate only the record-oriented subset in v1
- leave richer MemPalace semantics outside the base provider contract until they can be exposed honestly

That gives AgentMemory a more convincing multi-provider story without sacrificing architectural discipline.

## References

- MemPalace repository: <https://github.com/MemPalace/mempalace>
- MemPalace backend contract: <https://raw.githubusercontent.com/MemPalace/mempalace/develop/mempalace/backends/base.py>
- MemPalace memory stack concepts: <https://mempalace.github.io/mempalace/concepts/memory-stack.html>
