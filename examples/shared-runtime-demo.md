# Shared Runtime Demo

This is the canonical onboarding demo for AgentMemory.

It shows the most important current value of the project:

one memory backend exposed as one shared local runtime for different client surfaces.

## Goal

Write memory through the HTTP API and read it back through the CLI using the same runtime and scope.

## 1. Configure A Safe Demo Backend

```powershell
.\.venv\Scripts\agentmemory.exe configure --provider localjson
.\.venv\Scripts\agentmemory.exe doctor
.\.venv\Scripts\agentmemory.exe start-api
```

Success means:

- `doctor` reports no blocking errors
- `start-api` prints the API URL that the runtime is serving from

## 2. Write Through HTTP

```powershell
.\.venv\Scripts\python.exe .\examples\http_python_roundtrip.py
```

This script adds a memory record through the local API and then performs a list and search through the same API.

Success means:

- the script prints `Created memory`
- the script prints both `List result` and `Search result`

## 3. Read Through CLI

```powershell
.\.venv\Scripts\python.exe -m agentmemory.ops_cli list --user-id examples-http-roundtrip --limit 5
.\.venv\Scripts\python.exe -m agentmemory.ops_cli search "provider contracts" --user-id examples-http-roundtrip --limit 5 --no-rerank
```

Success means:

- the `list` command shows at least one memory for `examples-http-roundtrip`
- the `search` command returns the memory written through HTTP

## Why This Matters

Without AgentMemory, each surface would need to embed backend-specific behavior separately.

With AgentMemory:

- the API, CLI, and MCP surfaces talk to one runtime
- provider-specific behavior stays behind the provider adapter
- multiple tools can share the same backend and scope model

## Optional Next Step

Switch the provider to `mem0` and rerun the same flow:

```powershell
.\.venv\Scripts\agentmemory.exe configure --provider mem0 --openrouter-api-key "your-openrouter-key"
.\.venv\Scripts\agentmemory.exe doctor
.\.venv\Scripts\agentmemory.exe start-api
.\.venv\Scripts\python.exe .\examples\http_python_roundtrip.py
```

The point is not that the commands change. The point is that the client surface stays stable even when the backend changes.

## 5. Stop The Local API

```powershell
.\.venv\Scripts\agentmemory.exe stop-api
```
