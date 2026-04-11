# Shared Runtime Demo

This demo shows the most important current value of AgentMemory:

one memory backend exposed as one shared local runtime for different client surfaces.

## Goal

Write memory through the HTTP API and read it back through the CLI using the same runtime and scope.

## 1. Configure A Safe Demo Backend

```powershell
agentmemory configure --provider localjson
agentmemory doctor
agentmemory start-api
```

## 2. Write Through HTTP

```powershell
python .\examples\http_python_roundtrip.py
```

This script adds a memory record through the local API and then performs a list and search through the same API.

## 3. Read Through CLI

```powershell
agentmemory list --user-id examples-http-roundtrip --limit 5
agentmemory search "provider contracts" --user-id examples-http-roundtrip --limit 5 --no-rerank
```

## Why This Matters

Without AgentMemory, each surface would need to embed backend-specific behavior separately.

With AgentMemory:

- the API, CLI, and MCP surfaces talk to one runtime
- provider-specific behavior stays behind the provider adapter
- multiple tools can share the same backend and scope model

## Optional Next Step

Switch the provider to `mem0` and rerun the same flow:

```powershell
agentmemory configure --provider mem0 --openrouter-api-key "your-openrouter-key"
agentmemory doctor
agentmemory start-api
python .\examples\http_python_roundtrip.py
```

The point is not that the commands change. The point is that the client surface stays stable even when the backend changes.
