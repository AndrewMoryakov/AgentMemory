# Changelog

All notable changes to this project will be documented in this file.

The format is intentionally simple during public alpha.

## [Unreleased]

### Changed

- onboarding and quickstart docs now use explicit `.venv` command paths and a single canonical `localjson`-first shared-runtime flow
- `doctor` now treats a missing `.env` as informational instead of warning by default, which makes the `localjson` onboarding path less noisy

### Fixed

- Windows API lifecycle tracking now records the real listener PID instead of a launcher/shim PID
- API readiness no longer self-recurses through heavy `/health` diagnostics during startup
- API lifecycle recovery now handles matching untracked listeners more cleanly when PID/state files are missing
- shared-runtime onboarding docs now use the working `agentmemory.ops_cli` data-operation path instead of nonexistent top-level `agentmemory list/search` commands

## [0.1.1] - 2026-04-11

### Added

- first-class `list_scopes` support across runtime, API, CLI, MCP, and admin surfaces
- provider runtime transport policy as a public runtime contract
- profile-aware runtime config with named profiles such as `default` and `staging`
- runtime identity metadata in diagnostics
- stronger API runtime diagnostics for PID, port, and listener ownership
- formal `provider_contract()` V2 metadata for future provider integrations

### Changed

- repository layout is now package-first, with operational scripts in `scripts/`, snippets in `snippets/`, and provider/prelaunch docs in `docs/`
- proxy routing is driven by provider runtime policy instead of shared-layer `mem0` name checks
- `agentmemory start-api` now auto-selects a free port when the configured one is busy and updates runtime config accordingly
- `doctor` now reports active profile, runtime id, config version, API runtime state, and provider contract version

### Fixed

- `mem0` add/update response normalization for empty or partial result wrappers
- scope discovery for scope-required providers through `memory_list_scopes`
- stale or misleading port/process diagnostics by distinguishing foreign listener conflicts from stale PID records

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
