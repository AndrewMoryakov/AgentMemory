# AgentMemory

AgentMemory is a local shared-memory runtime for AI clients, scripts, and MCP-compatible tools.

It is not a new memory engine. It is the runtime layer around memory providers:

- shared HTTP API
- shared MCP server
- install and diagnostics CLI
- local client integration
- provider-based backend architecture

Current providers:

- `mem0`: production provider for long-term memory and semantic retrieval
- `localjson`: simple built-in provider for testing, demos, and architecture validation

## Why This Exists

Most AI tools can call MCP servers, shell commands, or HTTP APIs, but they still do not share a practical memory runtime by default.

AgentMemory turns one memory backend into one reusable local service for:

- Codex
- Claude Code
- Gemini CLI
- Qwen CLI
- Cursor
- VS Code / Copilot
- Roo Code
- KiloCode
- your own Python, PowerShell, or Node scripts

## What It Does

- exposes a local HTTP API for memory operations
- exposes a local stdio MCP server
- lets multiple clients reuse the same backend
- provides install, configure, doctor, and client auto-connect workflows
- exposes one interactive entrypoint with first-run onboarding and slash commands
- keeps the backend pluggable through providers
- normalizes provider behavior behind one typed provider contract
- shares one execution layer across CLI, HTTP API, and MCP
- now gives capability-aware diagnostics and client/runtime guidance
- now includes a built-in browser-based memory console for overview, exploration, pinning, editing, and delete flows

## Important Positioning

AgentMemory is:

- a local shared-memory runtime
- an integration and operations layer around memory providers
- a practical bridge between AI clients and a reusable memory backend

AgentMemory is not:

- a replacement for every provider it can host
- a new SOTA memory engine
- an enterprise multi-tenant service
- a full cross-platform desktop product today

## Current Status

- `public alpha`
- cross-platform Python runtime for Windows, macOS, and Linux
- Windows-first client integration workflow
- Python runtime that can also run in Docker
- provider-based core with a production `Mem0` path
- simple built-in `Local JSON` provider
- `Provider Contract V1` implemented
- shared operation registry and transport adapters implemented for core memory operations
- capability-aware diagnostics implemented in `doctor`, `status-clients`, `doctor-clients`, and the interactive home screen

## Architecture Snapshot

The core runtime is now split into explicit layers:

- provider contract: normalized `MemoryRecord` / `DeleteResult`, typed provider errors, and provider capabilities
- transport support: shared validation, error shaping, runtime/proxy dispatch, and MCP result formatting
- operation registry: one registry for `health/add/search/list/get/update/delete`
- operation adapters: transport-specific input normalization for CLI, MCP, and HTTP
- product surfaces: CLI, HTTP API, MCP server, interactive shell, and client integration workflows

In practical terms, the core memory operations now use:

- one provider contract
- one execution layer
- one runtime/proxy branching layer
- one transport input adaptation model

This is the main architectural baseline for future providers and transport surfaces.

## Platform Matrix

- Runtime core, HTTP API, and MCP server: Windows, macOS, Linux
- Docker API deployment: Linux containers, Docker Desktop, and compatible hosts
- Client auto-connect: Windows-first today
- PowerShell wrapper: Windows only
- POSIX shell launchers: macOS and Linux

## Key Design Choice For Mem0

`Mem0` uses local embedded storage by default in this project. Opening that storage from many short-lived processes can cause local lock contention.

AgentMemory avoids that by using an owner-process pattern for `mem0`:

- the local API process is the single owner of the Mem0 runtime
- CLI and MCP calls proxy to that API when `provider=mem0`
- this removes the main class of local `Qdrant` lock conflicts without modifying `Mem0`

That same architecture can later move to an external `Qdrant server` without redesigning the product surface.

## Quickstart

### Windows Local Setup

```powershell
git clone <your-repo-url>
cd AgentMemory
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
agentmemory configure --provider mem0 --openrouter-api-key "your-openrouter-key"
agentmemory doctor
agentmemory mcp-smoke
agentmemory connect-clients
agentmemory doctor-clients --compact
```

### Minimal Local Testing Provider

```powershell
agentmemory configure --provider localjson
agentmemory doctor
```

### Docker API Deployment

```powershell
docker compose up --build
```

If you want the `mem0` provider inside Docker, pass a real `OPENROUTER_API_KEY` into the container environment.

### macOS / Linux Local Setup

```sh
git clone <your-repo-url>
cd AgentMemory
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -e .
agentmemory configure --provider localjson
agentmemory doctor
agentmemory mcp-smoke
```

For the `mem0` provider on macOS or Linux:

```sh
agentmemory configure --provider mem0 --openrouter-api-key "your-openrouter-key"
agentmemory start-api
```

## Interactive Entry Point

The primary user entrypoint is now one command:

```powershell
agentmemory
```

Behavior:

- first run: interactive onboarding
- later runs: interactive shell with slash commands and a live command menu
- automation: the old subcommands still work

Examples inside the shell:

```text
/help
/doctor
/provider localjson
/start
/ui
/status
/clients
/exit

Type / in the shell to open the command menu. Use arrow keys to select and Enter to run.
```

## Core Commands

```powershell
agentmemory --help
agentmemory doctor
agentmemory configure --provider mem0 --openrouter-api-key "your-openrouter-key"
agentmemory configure --provider localjson
agentmemory configure --api-port 9777
agentmemory start-api
agentmemory stop-api
agentmemory mcp-smoke
agentmemory connect-clients
agentmemory status-clients --compact
agentmemory doctor-clients --compact
```

## Web Console

The local API now also serves a browser UI:

- `/`
- `/ui`

Phase 1 console capabilities:

- runtime overview
- memory explorer
- memory detail view
- edit memory text and metadata
- pin important memories
- delete low-value memories
- client status summary

Run the API and then open:

```text
http://127.0.0.1:8765/
```

## Configuration

Primary local config:

- `agentmemory.config.json`

Environment file:

- `.env`

Examples:

```powershell
agentmemory configure --provider mem0 --openrouter-api-key "your-openrouter-key"
agentmemory configure --provider localjson
agentmemory configure --api-host 127.0.0.1 --api-port 9777
```

Runtime API host and port can also be overridden through environment variables:

- `AGENTMEMORY_API_HOST`
- `AGENTMEMORY_API_PORT`

## Providers

### Mem0

Use `mem0` when you want:

- semantic memory retrieval
- OpenRouter-backed extraction and embeddings
- the main production path of this project

Notes:

- requires `OPENROUTER_API_KEY`
- uses the owner-process API pattern in this repo
- is the current default provider

### Local JSON

Use `localjson` when you want:

- zero external API dependency
- a simple built-in backend for tests and demos
- a provider that is easy to inspect on disk

Notes:

- stores records in a local JSON file
- no semantic model calls
- useful for validating the runtime architecture itself

## Provider Certification

AgentMemory uses a reusable provider contract harness and a typed `Provider Contract V1`.

If you add or change a provider, use:

- [PROVIDER_CERTIFICATION.md](PROVIDER_CERTIFICATION.md)
- [tests/provider_contract_harness.py](tests/provider_contract_harness.py)

Certification means a provider:

- returns normalized `MemoryRecord` / `DeleteResult` payloads
- enforces its declared capabilities
- throws typed provider errors
- passes the shared provider contract suite

The provider contract is no longer only an interface-level idea. The current runtime now depends on:

- provider capabilities for early validation and diagnostics
- typed provider errors for CLI, HTTP, and MCP error shaping
- certification helpers and CI policy checks for maintainers

Quick helper:

```powershell
agentmemory provider-certify --list
agentmemory provider-certify --list --json
agentmemory provider-certify localjson
agentmemory provider-certify localjson --json
agentmemory provider-certify localjson --run-tests
agentmemory provider-certify localjson --json --run-tests --summary-only
```

The helper prints a certification verdict plus unmet requirements, and `--json` gives the same result in a machine-readable form for scripts or CI. JSON output now also includes a `status_code` for stable automation decisions. With `--run-tests`, JSON output also includes a compact `test_summary`, and `--summary-only` suppresses the verbose test log. A direct `provider-certify` entrypoint is also available if you want to call the helper without the main CLI.

For policy-level CI checks across the main providers:

```powershell
provider-certify-ci --json
```

## HTTP API

Default bind:

- `127.0.0.1:8765`

Endpoints:

- `GET /health`
- `GET /memories`
- `GET /memories/{id}`
- `POST /add`
- `POST /search`
- `POST /update`
- `DELETE /memories/{id}`

Examples:

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8765/health"
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8765/search" -ContentType "application/json" -Body '{"query":"preferred style","user_id":"demo"}'
```

## MCP Server

Launchers:

- [run-agentmemory-mcp.ps1](run-agentmemory-mcp.ps1)
- [run-agentmemory-mcp.sh](run-agentmemory-mcp.sh)

Tools:

- `memory_health`
- `memory_add`
- `memory_search`
- `memory_list`
- `memory_get`
- `memory_update`
- `memory_delete`

## Supported Clients

Auto-connect currently covers:

- Codex
- Claude Code
- Claude Desktop
- Gemini CLI
- Qwen CLI
- Cursor
- VS Code / Copilot
- Roo Code
- KiloCode

`Cline` is detected separately and only configured when local extension storage exists.

On macOS and Linux, the runtime itself works, but client auto-connect is not yet implemented.

## Diagnostics

Human-readable:

```powershell
agentmemory status-clients --compact
agentmemory doctor-clients --compact
```

Machine-readable:

```powershell
agentmemory status-clients --json
agentmemory doctor-clients --json
```

Current diagnostics are capability-aware:

- `agentmemory doctor` now explains provider operational constraints, not only raw flags
- `agentmemory status-clients` now includes provider-aware client/runtime guidance in JSON mode
- `agentmemory doctor-clients` now includes both provider guidance and client/runtime guidance
- the interactive shell home screen now shows short provider notes when the current backend has operational constraints

Typical guidance includes:

- scope requirements for `search` / `list`
- stale launcher configuration warnings
- no-rerank guidance for simpler providers
- no-scopeless-browse guidance
- owner-process / local-runtime guidance for shared multi-client setups

`doctor-clients` exit codes:

- `0`: local MCP server healthy and all detected clients healthy
- `10`: local MCP server unhealthy, detected clients otherwise healthy
- `20`: local MCP server healthy, one or more detected clients unhealthy
- `30`: both local MCP server and one or more detected clients unhealthy

`not_detected` clients do not count as failures.

## Docker

Included files:

- [Dockerfile](Dockerfile)
- [docker-compose.yml](docker-compose.yml)

Default Docker behavior:

- API binds to `0.0.0.0:8765`
- local data persists through `./data:/app/data`
- uses the same provider-based runtime as local installs

Example:

```powershell
$env:OPENROUTER_API_KEY = "your-openrouter-key"
docker compose up --build
```

Then:

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8765/health"
```

## Security Notes

- designed for local or trusted self-hosted use
- HTTP API binds to localhost by default outside Docker
- `.env` is local-only and ignored by git
- `agentmemory.config.json` is local-only and ignored by git
- memory contents in `data/` should be treated as sensitive
- no multi-user auth or remote access control layer yet

## Limitations

- Windows-first client integration experience
- auto-connect is not implemented for macOS/Linux yet
- tests focus on smoke and interface stability, not exhaustive backend behavior
- `mem0` warnings from upstream dependencies still exist in some direct library paths
- Docker support is API-focused, not full desktop-client integration

## Development

Run tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Useful manual checks:

```powershell
agentmemory doctor
agentmemory mcp-smoke
agentmemory status-clients --compact
agentmemory doctor-clients --compact
```

Architecture-oriented checks:

```powershell
agentmemory provider-certify --list --json
agentmemory provider-certify mem0 --json --run-tests --summary-only
provider-certify-ci --json
```

## Repository Files

- [agentmemory.py](agentmemory.py)
- [agentmemory_runtime.py](agentmemory_runtime.py)
- [agentmemory_http_client.py](agentmemory_http_client.py)
- [agentmemory_api.py](agentmemory_api.py)
- [agentmemory_mcp_server.py](agentmemory_mcp_server.py)
- [agentmemory_clients.py](agentmemory_clients.py)
- [memory_provider.py](memory_provider.py)
- [mem0_provider.py](mem0_provider.py)
- [localjson_provider.py](localjson_provider.py)
- [agentmemory_admin.py](agentmemory_admin.py)
- [Dockerfile](Dockerfile)
- [docker-compose.yml](docker-compose.yml)
- [run-agentmemory-mcp.sh](run-agentmemory-mcp.sh)
- [start-agentmemory-api.sh](start-agentmemory-api.sh)
- [ROADMAP.md](ROADMAP.md)
- [.env.example](.env.example)
- [LICENSE](LICENSE)

