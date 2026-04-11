# Prelaunch Risks

This document records the main technical risks that should be understood before positioning AgentMemory as a mature community project or describing it in public media as a production-ready universal memory runtime.

## Why This Exists

AgentMemory already has the right high-level shape:

- a shared contract
- multiple transports
- provider adapters
- contract tests

The risks below are not arguments against the architecture. They are the places where the current implementation still relies on shortcuts, implicit assumptions, or provider-specific behavior that can break the public narrative if left undocumented.

## Risk 1: `mem0` scope inventory is implemented through backend internals

### What is happening

`list_scopes` for `mem0` is currently implemented by reading qdrant-backed local storage directly:

- open `storage.sqlite`
- fetch raw `points`
- unpickle blobs
- extract `payload.user_id`, `payload.agent_id`, `payload.run_id`

This is not a supported upstream API contract from `mem0`. It is an implementation-level workaround.

### Why this is a problem

- It couples AgentMemory to private storage details of `mem0` and `qdrant_client`.
- A dependency update can silently break `list_scopes` without changing the AgentMemory contract.
- The provider is no longer acting purely as an adapter over supported backend behavior.
- `pickle` is not a safe format for untrusted input and should be treated carefully.

### What this can lead to

- scope discovery suddenly breaking after dependency upgrades
- hard-to-debug regressions that only appear on specific local data layouts
- confusion in the community when a documented feature works only for one exact provider/version combination
- security concerns if users assume the system safely parses arbitrary persisted data

### Why it matters for public messaging

If AgentMemory is described as a universal provider layer, this feature makes the `mem0` integration look more stable and provider-native than it really is.

## Risk 2: HTTP API has no authentication, while exposing admin and write operations

### What is happening

The local HTTP API exposes:

- memory read endpoints
- memory write/update/delete endpoints
- admin endpoints

There is currently no authentication layer on these endpoints.

By default the project is usually used on localhost, which keeps this acceptable for local workflows. But the runtime also supports configurable bind host and port.

### Why this is a problem

- The security model depends on deployment discipline rather than enforced policy.
- If a user binds the API to `0.0.0.0` or any non-local interface, the service can become remotely reachable with no auth barrier.
- The most sensitive endpoints are the same ones the project exposes for operational convenience.

### What this can lead to

- remote reading of memory contents
- remote modification or deletion of memory
- accidental exposure of internal notes, user data, or operational metadata
- support incidents caused by users following examples without understanding network implications

### Why it matters for public messaging

If articles or docs present AgentMemory as a server component without clearly stating the localhost-only trust model, people may deploy it in unsafe ways.

## Risk 3: proxy behavior is still partially hard-coded to `mem0`

### What is happening

The HTTP proxy behavior currently contains logic equivalent to:

- if active provider is `mem0`
- and current process is not the owner process
- use the local API as a proxy path

This works for current `mem0` locking/runtime behavior, but it is provider-name specific.

### Why this is a problem

- Shared transport logic still knows concrete backend identity.
- Future providers with the same owner-process constraint will require more provider-name branching.
- The runtime policy is not fully expressed as capabilities or execution semantics.

### What this can lead to

- architecture drift away from provider-neutral design
- accumulating `if provider == ...` branches in shared layers
- more difficult onboarding of new backends such as `Qdrant-native`, `Chroma`, or `LanceDB`

### Why it matters for public messaging

If AgentMemory is described as a generic provider runtime, the transport layer should act on capabilities and policies, not provider names.

## Risk 4: public narrative can overstate readiness

### What is happening

The project is already strong as:

- a local memory runtime
- a provider adapter architecture
- a testable contract layer
- an evolving MCP bridge

But some capabilities are still transitional or operationally constrained.

### Why this is a problem

- Readers often interpret architecture diagrams as readiness claims.
- Community users will test edge cases first.
- Articles tend to flatten nuance unless limitations are stated explicitly.

### What this can lead to

- trust erosion if “universal” sounds stronger than the actual current guarantees
- bug reports caused by unsupported deployment assumptions
- pressure to maintain compatibility with accidental behavior instead of intentional contracts

## Recommended Positioning Until These Risks Are Addressed

Safe public framing right now:

- AgentMemory is a universal memory runtime architecture with multiple transports and provider adapters.
- `localjson` is the clean reference provider.
- `mem0` integration is supported, but some operational behavior remains provider-specific.
- the HTTP API is intended for local trusted environments unless additional security controls are added.

Risky framing right now:

- “production-ready universal memory server”
- “secure multi-user memory service”
- “fully provider-agnostic runtime” without caveats

