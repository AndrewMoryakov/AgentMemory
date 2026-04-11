# AgentMemory

AgentMemory is a shared local memory runtime for AI clients and agents.

It sits above a memory backend such as `mem0` and exposes one stable surface through CLI, HTTP API, and MCP.

If you only need one Python application talking directly to a memory engine, direct `mem0` integration is often enough.

If memory needs to behave like shared local infrastructure for multiple tools, scripts, and agent clients, that is where AgentMemory adds value.

## Why This Project Exists

Most memory systems solve the backend problem: storing, retrieving, and ranking memories.

AgentMemory solves a different problem: making one memory backend usable as one local runtime across multiple client surfaces.

That includes:

- CLI workflows
- local HTTP API access
- MCP tool access
- browser-based inspection
- diagnostics and runtime guidance
- provider-aware transport behavior

This is the main distinction:

- `mem0` is a memory engine
- `AgentMemory` is a memory runtime layer

Start here if you want the fuller explanation:

- [Why AgentMemory Exists](docs/WHY_AGENTMEMORY.md)
- [Mem0 vs AgentMemory](docs/MEM0_VS_AGENTMEMORY.md)
- [Start Here](docs/START_HERE.md)

## When You Probably Do Not Need AgentMemory

You probably do not need AgentMemory if:

- one Python application owns memory directly
- direct provider integration is already clean
- you do not need MCP or HTTP access
- you do not need several tools to share one runtime

In that case, direct `mem0` integration is usually simpler.

## When AgentMemory Is Useful

AgentMemory becomes useful when one memory backend must serve many surfaces consistently.

Strong current examples:

- one backend reused by CLI, MCP, scripts, and browser tooling
- one owner process for a backend with local runtime constraints
- one stable contract above backend-specific quirks

More concrete scenarios:

- [Use Cases](docs/USE_CASES.md)
- [Shared Runtime Demo](examples/shared-runtime-demo.md)
- [MCP Demo](examples/mcp-demo.md)

## Quickstart

### Fastest Safe Evaluation Path

Use the built-in `localjson` provider first.

```powershell
git clone <your-repo-url>
cd AgentMemory
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
agentmemory configure --provider localjson
agentmemory doctor
agentmemory start-api
python .\examples\http_python_roundtrip.py
```

This path proves:

- package install works
- the local runtime starts
- the HTTP API works
- one client surface can read and write memory immediately

### Local Runtime Files

AgentMemory generates local runtime state during setup and use.

These files are local-only and should not be committed:

- `.env`
- `agentmemory.config.json`
- `data/`

The repository only ships safe templates such as `.env.example`.

### Main Semantic Backend

If you want the main semantic path, switch to `mem0`:

```powershell
agentmemory configure --provider mem0 --openrouter-api-key "your-openrouter-key"
agentmemory doctor
agentmemory start-api
```

### macOS / Linux

```sh
git clone <your-repo-url>
cd AgentMemory
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -e .
agentmemory configure --provider localjson
agentmemory doctor
agentmemory start-api
python ./examples/http_python_roundtrip.py
```

## Architecture Snapshot

```mermaid
flowchart TD
    A["Clients and Tools"] --> B["CLI / HTTP API / MCP / Browser UI"]
    B --> C["Shared Runtime Layer"]
    C --> D["Provider Contract"]
    D --> E["Providers: mem0, localjson, future providers"]
```

Current runtime layers:

- provider contract: normalized records, typed provider errors, capabilities, runtime policy
- shared runtime: operation registry, adapters, validation, error shaping, proxy/direct routing
- surfaces: CLI, HTTP API, MCP, interactive shell, browser UI

More detail:

- [Architecture](docs/ARCHITECTURE.md)
- [Provider Adapter Rules](docs/PROVIDER_ADAPTER_RULES.md)
- [Future Memory Providers](docs/future-memory-providers/README.md)

## Current Status

- `public alpha`
- local-first product
- runtime core works on Windows, Linux, and expected macOS paths
- Windows-first client integration workflow
- `mem0` is the main semantic provider
- `localjson` is the built-in testing and demo provider
- provider contract, operation registry, transport adapters, and runtime policy are implemented
- diagnostics and scope discovery are part of the current product surface

## Key Design Choice For Mem0

`mem0` uses local embedded storage in this project, and local embedded backends can have process and lock constraints.

AgentMemory handles that by giving the provider an explicit runtime transport policy:

- the local API process can own the backend runtime
- other clients can proxy through that runtime
- shared layers do not need backend-specific branching for transport behavior

This is one of the clearest examples of why a memory runtime layer can be useful even when the backend is still `mem0`.

## Main Commands

```powershell
agentmemory --help
agentmemory doctor
agentmemory configure --provider localjson
agentmemory configure --provider mem0 --openrouter-api-key "your-openrouter-key"
agentmemory start-api
agentmemory stop-api
agentmemory mcp-smoke
agentmemory connect-clients
agentmemory status-clients --compact
agentmemory doctor-clients --compact
```

## Browser UI

The local API also serves a browser UI at:

```text
http://127.0.0.1:8765/
```

Current browser UI capabilities:

- runtime overview
- memory explorer
- memory detail view
- edit memory text and metadata
- pin important memories
- delete low-value memories
- client status summary

## Providers

### Mem0

Use `mem0` when you want:

- semantic retrieval
- OpenRouter-backed extraction and embeddings
- the main production path of this repo

Notes:

- requires `OPENROUTER_API_KEY`
- uses owner-process proxy transport in this repo
- is the current default provider

### Local JSON

Use `localjson` when you want:

- zero external API dependency
- a simple built-in backend for tests and demos
- an inspectable on-disk provider

## Documentation Map

- [Start Here](docs/START_HERE.md)
- [Why AgentMemory Exists](docs/WHY_AGENTMEMORY.md)
- [Mem0 vs AgentMemory](docs/MEM0_VS_AGENTMEMORY.md)
- [Use Cases](docs/USE_CASES.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Positioning Assets](docs/POSITIONING.md)
- [Roadmap](ROADMAP.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [Support](SUPPORT.md)

## Examples

- [HTTP Python Roundtrip](examples/http_python_roundtrip.py)
- [Shared Runtime Demo](examples/shared-runtime-demo.md)
- [MCP Demo](examples/mcp-demo.md)

## Validation

Useful local checks:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall agentmemory tests scripts/mcp-smoke-test.py
agentmemory mcp-smoke
```

## Provider Certification

AgentMemory treats providers as adapter layers behind one shared contract.

Useful references:

- [PROVIDER_CERTIFICATION.md](docs/PROVIDER_CERTIFICATION.md)
- [tests/provider_contract_harness.py](tests/provider_contract_harness.py)

Quick helper commands:

```powershell
agentmemory provider-certify --list
agentmemory provider-certify --list --json
agentmemory provider-certify localjson
agentmemory provider-certify localjson --json --run-tests --summary-only
```
