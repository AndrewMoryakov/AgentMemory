# Provider Adapter Rules

AgentMemory is a stable memory runtime contract over unstable backend implementations.

That means a provider in this project is an adapter layer, not a thin wrapper around an SDK or API.

## Core Rule

Upstream SDKs and APIs are not the AgentMemory contract.

Each provider must absorb backend-specific behavior and expose one stable AgentMemory contract to:

- CLI
- HTTP API
- MCP server
- interactive shell
- external clients

## Provider Responsibilities

Every provider must handle these concerns inside the provider layer.

### 1. Input Adaptation

Providers accept only normalized AgentMemory operation inputs:

- `add_memory(messages, user_id, agent_id, run_id, metadata, infer, memory_type)`
- `search_memory(query, user_id, agent_id, run_id, limit, filters, threshold, rerank)`
- `list_memories(user_id, agent_id, run_id, limit, filters)`
- `get_memory(memory_id)`
- `update_memory(memory_id, data, metadata)`
- `delete_memory(memory_id)`

Transport layers should not shape requests differently for different providers.

### 2. Output Normalization

Providers must always return AgentMemory contract payloads.

They must never leak raw backend response shapes directly to transport layers.

Examples of backend-specific payloads that must be normalized internally:

- `{"results": [...]}`
- `{"items": [...]}`
- `{"matches": [...]}`
- `{"message": "success"}`
- partial objects with only `id` and `event`
- empty arrays on successful no-op operations
- async job handles or delayed write acknowledgements

The provider must convert these into:

- `MemoryRecord`
- `list[MemoryRecord]`
- `DeleteResult`

### 3. Error Mapping

Providers must map backend exceptions and error payloads into typed AgentMemory errors:

- `ProviderConfigurationError`
- `ProviderCapabilityError`
- `ProviderScopeRequiredError`
- `ProviderUnavailableError`
- `ProviderValidationError`
- `MemoryNotFoundError`

Transport layers should not need backend-specific error parsing.

### 4. Capability Declaration

Each provider must accurately declare its capabilities through `capabilities()`.

These flags are contract-level behavior, not marketing statements.

Examples:

- semantic vs text search
- filter support
- rerank support
- update/delete support
- scopeless list/search support
- owner-process requirements

If a provider cannot reliably support a feature, it must declare that feature unsupported.

### 5. Scope Semantics

If a backend requires `user_id`, `agent_id`, or `run_id`, the provider must enforce that clearly.

The rest of the runtime should not need to know backend-specific scope rules beyond declared capabilities and typed errors.

### 6. No-Op Semantics

Providers must define what success means when no material change happens.

Examples:

- add request produced no new memory
- update request deduplicated into existing content
- backend returned `NONE`
- delete request reported success without a rich payload

No-op success must not be surfaced as an arbitrary validation failure unless the backend result is genuinely unusable.

### 7. Fallback and Hydration

Providers may need defensive fallback logic when a backend returns a partial success payload.

Examples:

- hydrate a minimal `{"id","event"}` add result via `get(id)`
- recover a full updated record after a message-only success response
- recover a just-added record through scoped list/get when the backend confirms success but omits the full object

Fallback logic belongs in the provider, not in API/MCP/CLI layers.

### 8. Concurrency Model

If a backend has process, file-lock, or connection-pool constraints, the provider must surface that through:

- capabilities
- diagnostics
- typed availability errors
- runtime guidance

Infrastructure workarounds such as owner-process mode are acceptable when they remain outside the provider contract and do not leak backend details into general transport behavior.

## Architecture Boundaries

These layers must remain backend-agnostic:

- `agentmemory/runtime/operations.py`
- `agentmemory/runtime/transport.py`
- `agentmemory/api.py`
- `agentmemory/mcp.py`
- `agentmemory/runtime/http_client.py`

These layers may contain backend-specific logic:

- `<provider>_provider.py`
- provider certification helpers if they are explicitly provider-scoped

Avoid patterns like:

- `if provider_name == "mem0"` in transport or API layers
- provider-specific response parsing outside provider modules
- provider-specific error wording checks in shared layers

## Provider Maturity Checklist

A provider is not integration-ready until it has:

- canonical result mapping for all CRUD operations
- typed error mapping
- accurate capability declaration
- explicit scope semantics
- documented no-op behavior
- fallback strategy for partial success payloads
- concurrency/runtime guidance where relevant
- contract tests

## Recommended Test Cases For Every Provider

Each provider should be tested for:

- add returns canonical `MemoryRecord`
- search returns canonical ranked results
- list returns canonical records
- get/update/delete return canonical payloads
- missing record operations raise `MemoryNotFoundError`
- unsupported capabilities raise the right typed errors
- scope requirements are enforced consistently
- backend partial success payloads are normalized correctly
- backend message-only success payloads are normalized correctly
- no-op add/update/delete behavior is stable and intentional

## Design Principle

AgentMemory should be the stable system.

Backends may be inconsistent, incomplete, chatty, eventually consistent, or operationally awkward.

That inconsistency must terminate at the provider boundary.
