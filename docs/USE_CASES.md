# Use Cases

These are the strongest present-day use cases for AgentMemory.

## 1. One Backend, Many Clients

Problem:

You want `Codex`, local scripts, CLI workflows, and MCP clients to share one memory backend.

Why direct provider integration is awkward:

- not every client can import the backend SDK
- each tool would need separate setup and configuration
- behavior and error handling drift across integrations

Why AgentMemory helps:

- one HTTP API
- one MCP server
- one CLI
- one provider contract for all surfaces

## 2. Owner-Process Runtime For Fragile Local Backends

Problem:

A backend uses local embedded storage and should not be opened independently by many short-lived processes.

Current real example:

- the `mem0` setup in this repo

Why direct use can be awkward:

- lock contention
- duplicated initialization
- inconsistent local environment state

Why AgentMemory helps:

- one local owner process
- other tools proxy through that runtime
- transport behavior is expressed as provider runtime policy

## 3. Shared Memory For Agent Tooling

Problem:

You want memory to be available inside MCP-style agent environments, not just inside one app process.

Why AgentMemory helps:

- MCP-native tool exposure
- typed structured errors
- one stable operation surface
- same runtime accessible from CLI and API for debugging

## 4. Memory As Local Infrastructure

Problem:

You want memory to be a reusable local system component, not a one-off library integration.

Why AgentMemory helps:

- health checks
- doctor workflows
- local admin and inspection
- configuration and runtime visibility

This is useful for teams or individuals who treat agent tooling as a real local stack.

## 5. Future Provider Swapping Without Rewriting Clients

Problem:

You may start with `mem0`, but later want another backend.

Why AgentMemory helps:

- clients talk to AgentMemory, not directly to each backend
- backend-specific quirks terminate at the provider adapter
- switching cost is lower than re-integrating every client separately

This is a secondary benefit, not the main pitch today.
