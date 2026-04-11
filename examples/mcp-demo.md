# MCP Demo

This demo shows how AgentMemory fits MCP-style agent workflows.

## Goal

Expose memory as MCP tools so an agent can add, search, list, and inspect shared memory without importing a provider SDK directly.

## 1. Validate The MCP Surface

```powershell
agentmemory mcp-smoke
```

That checks the local MCP tool surface and basic request/response flow.

## 2. Start The Local Runtime

```powershell
agentmemory configure --provider localjson
agentmemory start-api
```

## 3. Expected MCP Tool Shape

Current core tools:

- `memory_health`
- `memory_add`
- `memory_search`
- `memory_list`
- `memory_get`
- `memory_update`
- `memory_delete`
- `memory_list_scopes`

## 4. Why This Matters

An MCP client does not need to know:

- how `mem0` is configured
- how provider errors are normalized
- whether the provider needs owner-process proxying
- how scopes are represented internally

It only needs the AgentMemory tool contract.

## 5. What This Proves

AgentMemory is not just a Python wrapper around a backend.

It is a runtime surface that makes memory available to agent ecosystems that prefer:

- tools
- HTTP
- CLI

instead of direct SDK imports.
