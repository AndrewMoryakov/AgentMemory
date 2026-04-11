# Announcement Pack

This file contains reusable public-facing announcement text for AgentMemory.

The goal is to make it easy to publish:

- GitHub release notes
- a short Telegram or X post
- a Reddit or Hacker News intro
- a project launch summary without rewriting the core message each time

## Core Message

`AgentMemory` is a shared local memory runtime for AI clients and agents.

It sits above a memory backend and exposes one consistent surface through CLI, HTTP API, and MCP, so multiple tools can use the same memory system without each one embedding backend-specific integration logic.

If you already have one Python app directly using a memory engine, that may be enough. But when memory needs to be shared across scripts, local tools, MCP clients, browser tooling, and agent workflows, `AgentMemory` becomes the useful layer on top.

## Why Not Just Mem0

That is a fair question, and in many cases the honest answer is: you probably should just use `mem0` directly.

`mem0` solves the backend problem: storing and retrieving memory.

`AgentMemory` solves a different problem: turning that backend into shared local infrastructure that multiple tools can access consistently. It adds the runtime layer around memory: CLI, HTTP API, MCP, diagnostics, provider contract normalization, and provider-aware runtime behavior.

## What Is Already Here

- shared local runtime exposed through CLI, HTTP API, and MCP
- provider-based architecture with `mem0` as the main semantic path and `localjson` as a built-in testing/demo provider
- diagnostics and operator-friendly surfaces including `doctor`, `mcp-smoke`, typed errors, scope discovery, and browser-based inspection

## Demo Commands

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
agentmemory configure --provider localjson
agentmemory doctor
agentmemory start-api
.\.venv\Scripts\python.exe .\examples\http_python_roundtrip.py
agentmemory mcp-smoke
```

## GitHub Release Version

`AgentMemory` is a shared local memory runtime for AI clients and agents. It exposes one stable surface through CLI, HTTP API, and MCP, and sits above pluggable backend providers such as `mem0`.

This project is not trying to replace memory engines. The idea is simpler: many tools can use one shared runtime without each one integrating backend-specific logic separately. If you only need one Python application talking directly to `mem0`, that may already be enough. But if memory needs to be reused across scripts, local tools, MCP clients, and agent workflows, `AgentMemory` becomes the useful layer on top.

Included in this public alpha:

- shared runtime through CLI, HTTP API, and MCP
- provider-based core with `mem0` and `localjson`
- diagnostics, scope discovery, browser UI, certification tooling, and runtime profiles

Recent improvements since the first public alpha:

- `memory_list_scopes` for scope discovery in scope-required providers
- runtime transport policy separated cleanly from provider-name branching
- automatic free-port selection for local API startup
- stronger runtime diagnostics for profile, PID, port ownership, and listener conflicts
- formal provider contract `v2` metadata for future provider integrations

Quick local path:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
agentmemory configure --provider localjson
agentmemory doctor
agentmemory start-api
.\.venv\Scripts\python.exe .\examples\http_python_roundtrip.py
agentmemory mcp-smoke
```

## X / Telegram Version

Built `AgentMemory`: a shared local memory runtime for AI clients and agents.

It is not a new memory engine. It is the runtime layer around one:

- CLI
- HTTP API
- MCP
- shared local workflows

If one Python app already uses `mem0` directly, that may be enough. But if memory needs to be shared across scripts, tools, MCP clients, and local agent workflows, this is the layer that makes that practical.

Already includes:

- `mem0` + `localjson`
- `doctor`, `mcp-smoke`, scope discovery
- browser UI and provider-aware runtime behavior

## Reddit / HN Intro Version

I have been building `AgentMemory`, a local shared memory runtime for AI clients and agents.

The point is not to replace something like `mem0`. The point is to make a memory backend usable as shared local infrastructure across multiple surfaces: CLI, HTTP API, MCP, local scripts, and browser tooling. If one Python app directly using `mem0` is enough, that is still the simpler path. But once memory has to be reused across multiple tools, the runtime layer starts to matter.

Current state:

- shared local runtime through CLI / HTTP / MCP
- provider-based core with `mem0` and `localjson`
- diagnostics, scope discovery, browser UI, and contract/certification work

Quick path to try it:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
agentmemory configure --provider localjson
agentmemory doctor
agentmemory start-api
.\.venv\Scripts\python.exe .\examples\http_python_roundtrip.py
agentmemory mcp-smoke
```
