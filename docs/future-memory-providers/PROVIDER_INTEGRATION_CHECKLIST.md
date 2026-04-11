# Provider Integration Checklist

Use this checklist when evaluating or implementing a future memory source for AgentMemory.

## Stage 1: Initial Fit Assessment

- Identify the tool name and primary purpose.
- Classify it as one of:
  - `record provider`
  - `graph provider`
  - `hybrid provider`
  - `companion tool`
- Identify whether the tool exposes:
  - a Python SDK
  - an HTTP API
  - a CLI only
  - embedded/local storage only
- Decide whether it is a realistic near-term integration or a research/experimental target.

## Stage 2: Contract Mapping

- Define the canonical unit that AgentMemory will expose as a `MemoryRecord`.
- Determine whether the backend has stable ids.
- Determine whether the backend can support:
  - `add`
  - `search`
  - `list`
  - `get`
  - `update`
  - `delete`
  - `list_scopes`
- Decide which operations are:
  - fully supported
  - partially supported
  - unsupported

## Stage 3: Scope Strategy

- Determine whether the provider supports native scope concepts.
- Determine whether the provider requires scope for reads or writes.
- Determine whether native scope inventory exists.
- If native scope inventory does not exist, decide whether:
  - AgentMemory shared scope registry will be used
  - `supports_scope_inventory = False`

Do not rely on provider-private storage internals unless the integration is explicitly marked experimental.

## Stage 4: Capability Declaration

- Define `supports_semantic_search`
- Define `supports_text_search`
- Define `supports_filters`
- Define `supports_metadata_filters`
- Define `supports_rerank`
- Define `supports_update`
- Define `supports_delete`
- Define `supports_scopeless_list`
- Define `requires_scope_for_list`
- Define `requires_scope_for_search`
- Define `supports_owner_process_mode`
- Define `supports_scope_inventory`

Capabilities must describe real behavior, not desired future behavior.

## Stage 5: Transport Policy

- Determine whether the provider can be called directly from multiple local clients.
- Determine whether the provider needs an owner process or proxy mode.
- Determine whether the provider is inherently remote-only.
- Define the intended transport policy.

Recommended policy vocabulary:

- `direct`
- `owner_process_proxy`
- `remote_only`

Avoid implementing transport decisions by provider name.

## Stage 6: Provider Implementation

- Implement provider input adaptation.
- Implement output normalization.
- Implement typed error mapping.
- Implement any fallback or hydration logic.
- Implement diagnostics and health metadata where needed.
- Keep all backend-specific logic in the provider module.

## Stage 7: Tests

- Add contract-level tests.
- Add provider-specific normalization tests.
- Add scope behavior tests.
- Add transport policy tests if the provider has special runtime constraints.
- Add negative-path tests for unsupported operations.
- Add tests for partial success payloads if the upstream backend is inconsistent.

## Stage 8: Maturity Classification

Choose one:

- `reference`
- `supported`
- `experimental`

Suggested rule of thumb:

- `reference`: clean, stable, fully controlled behavior
- `supported`: real backend integration with solid contract fidelity
- `experimental`: useful but semantically incomplete, unstable, or operationally awkward

## Stage 9: Documentation

- Document the provider type.
- Document capability differences from `localjson`.
- Document scope behavior.
- Document transport/runtime constraints.
- Document known limitations.
- Document whether restarts are needed after configuration changes.

## Stage 10: Final Review Questions

- Does the provider fit the AgentMemory architecture, or is AgentMemory bending around it?
- Are unsupported features declared honestly?
- Is any shared layer leaking provider-specific knowledge?
- Would a future provider need to copy this provider's hacks to integrate?
- Is the user-facing narrative stronger than the implementation actually supports?

If any answer is uncomfortable, the provider is not ready to be described as fully supported.

