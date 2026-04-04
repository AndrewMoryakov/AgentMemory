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
- keeps the backend pluggable through providers

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
- [Dockerfile](Dockerfile)
- [docker-compose.yml](docker-compose.yml)
- [run-agentmemory-mcp.sh](run-agentmemory-mcp.sh)
- [start-agentmemory-api.sh](start-agentmemory-api.sh)
- [.env.example](.env.example)
- [LICENSE](LICENSE)
