# Positioning Assets

This file contains reusable public-facing wording for the repository, docs, and later media posts.

## One-Sentence Description

AgentMemory is a shared local memory runtime for AI clients and agents, exposed through CLI, HTTP API, and MCP, with pluggable backend providers such as `mem0`.

## 50-Word Repo Intro

AgentMemory turns a memory backend into reusable local infrastructure for AI tools. It adds one shared runtime layer above providers like `mem0`, exposes memory through HTTP, CLI, and MCP, and helps multiple clients use the same memory system consistently without each tool embedding backend-specific integration logic.

## 150-Word Repo Intro

AgentMemory is a local shared-memory runtime for AI tools, agents, scripts, and MCP-compatible clients. It is not a replacement for `mem0` or another memory engine. Instead, it sits above a memory provider and turns that backend into reusable local infrastructure.

This matters when memory is no longer used by just one Python process. If you want MCP clients, local scripts, browser tooling, and CLI workflows to share one memory runtime, direct SDK integration becomes awkward. AgentMemory gives those surfaces one contract and one operational layer: HTTP API, MCP server, CLI workflows, diagnostics, scope discovery, and provider-aware runtime behavior.

If one Python app owns memory cleanly, direct `mem0` integration is often enough. But if memory needs to be shared across tools and agents, AgentMemory becomes the useful layer on top.

## When To Use Mem0 Directly

Use `mem0` directly when one Python application owns memory and can configure the backend cleanly inside its own process. That is simpler, and for many projects it is the right answer.

## When AgentMemory Adds Value

AgentMemory adds value when memory must behave like shared local infrastructure for multiple tools, MCP clients, scripts, and agent workflows, while hiding backend-specific runtime quirks behind one stable contract.

## FAQ

### Why not just use mem0?

Often you should. If one Python application owns memory directly, `mem0` may be enough. AgentMemory is useful when several tools need to share one runtime through CLI, HTTP, or MCP.

### Is AgentMemory a multi-provider runtime today?

Yes at the architecture level, but that is not the primary public value. The stronger current value is a shared local runtime around the memory backend you already want to use.

### Is this local-only?

The current product is local-first and should be described that way publicly. Docker API deployment is available, but this is not positioned as a hosted multi-tenant platform.

### Who is this for right now?

Primarily AI tool builders and local agent-stack developers who want memory available through MCP, CLI, scripts, and HTTP without forcing each tool to embed provider-specific logic.
