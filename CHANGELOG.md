# Changelog

All notable changes to this project will be documented in this file.

The format is intentionally simple during public alpha.

## [0.1.0] - 2026-04-04

Initial public alpha release.

### Added

- product-style `agentmemory` CLI for install, configuration, diagnostics, API control, and client integration
- provider-based runtime architecture with a production `Mem0Provider`
- built-in `LocalJsonProvider` for local testing and provider-layer validation
- local MCP server over the provider runtime
- local HTTP API over the provider runtime
- generic runtime config in `agentmemory.config.json`
- owner-process proxy path for `Mem0`, so CLI and MCP can reuse a single local API process instead of opening local Qdrant in each process
- configurable API host and port through runtime config and environment overrides
- Dockerfile and `docker-compose.yml` for API deployment
- POSIX shell launchers for the runtime, MCP server, and local API lifecycle
- OpenRouter-based Mem0 provider defaults using `google/gemma-4-31b-it` and `google/gemini-embedding-001`
- auto-connect support for Codex, Claude Code, Claude Desktop, Gemini CLI, Qwen CLI, Cursor, VS Code/Copilot, Roo Code, and KiloCode
- `status-clients` and `doctor-clients` commands with compact, table, and JSON output
- stable `doctor-clients` exit codes for scripting
- baseline automated tests for CLI behavior, output normalization, exit-code mapping, and MCP protocol smoke behavior
- public-alpha README, packaging metadata, MIT license, and contribution guide

### Notes

- runtime core, MCP server, and HTTP API now have a cross-platform launch path
- client auto-connect remains Windows-first
- real OpenRouter-backed memory mutation/search remains a manual integration validation path
