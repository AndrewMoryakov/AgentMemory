# Mem0 vs AgentMemory

This is the practical decision guide.

## Short Version

- `mem0` is the memory engine
- `AgentMemory` is the shared runtime around a memory engine

They are not the same product category.

## Use `mem0` Directly When

`mem0` is usually enough if:

- one Python application owns memory
- that application can import and configure the SDK directly
- you do not need MCP or HTTP access
- you do not need multiple clients to share one runtime
- you are comfortable managing backend-specific setup inside the app itself

This is the simplest path and often the right one.

## Use AgentMemory When

`AgentMemory` adds value when:

- multiple tools need to use the same memory
- some of those tools are MCP clients, CLIs, scripts, or non-Python integrations
- you want one HTTP, CLI, and MCP surface for memory operations
- you want one local owner process for a backend with runtime constraints
- you want diagnostics, health checks, typed errors, scope discovery, and admin flows above the backend
- you want the option to change providers later without rewriting every client integration

## The Core Difference

### `mem0`

Focus:

- storing memories
- semantic retrieval
- provider-specific memory behavior
- embeddings and extraction behavior

Main question it answers:

"How does this backend store and retrieve memory?"

### `AgentMemory`

Focus:

- exposing one stable memory contract through CLI, HTTP API, and MCP
- turning memory into reusable local infrastructure
- hiding backend quirks behind provider adapters
- giving multiple clients one shared runtime
- adding diagnostics and operational visibility

Main question it answers:

"How do multiple tools and agents use one memory backend safely and consistently?"

## Concrete Example

If you have:

- one Python agent
- one codebase
- direct control of runtime setup

Then direct `mem0` integration is probably the better choice.

If you have:

- Codex or other MCP-based tools
- local scripts
- a browser console
- CLI workflows
- multiple agents touching the same memory runtime

Then `AgentMemory` is the better fit.

## Honest Positioning

`AgentMemory` should not be pitched as "better than mem0".

The honest positioning is:

- `mem0` solves the backend problem
- `AgentMemory` solves the shared-runtime and multi-client integration problem

That is the real distinction.

If you want the product-facing version of the same story, read
[What AgentMemory Adds To Mem0](MEM0_WITH_AGENTMEMORY_VALUE.md).
