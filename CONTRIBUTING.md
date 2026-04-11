# Contributing

Thanks for contributing to AgentMemory.

This project is currently a `public alpha` with a cross-platform runtime and a Windows-first client integration workflow, so contributions should prioritize clarity, stability, and local operability over broad abstraction.

The current architecture now assumes:

- `Provider Contract V1` is a real contract surface
- core memory operations run through a shared operation registry
- CLI, HTTP API, and MCP are expected to reuse shared transport logic and adapters
- capability-aware diagnostics are user-facing behavior, not optional polish

## Local setup

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

POSIX shell equivalent:

```sh
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -e .
```

Optional local configuration:

```powershell
agentmemory configure --openrouter-api-key "your-openrouter-key"
```

## Validation before changes are submitted

Run these checks locally:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m py_compile agentmemory.py agentmemory_runtime.py agentmemory_clients.py agentmemory_api.py agentmemory_cli.py agentmemory_mcp_server.py mem0_provider.py memory_provider.py
agentmemory mcp-smoke
agentmemory doctor-clients --compact
```

POSIX shell equivalent:

```sh
./.venv/bin/python -m unittest discover -s tests -v
./.venv/bin/python -m py_compile agentmemory.py agentmemory_runtime.py agentmemory_clients.py agentmemory_api.py agentmemory_cli.py agentmemory_mcp_server.py mem0_provider.py memory_provider.py
agentmemory mcp-smoke
```

If your change affects packaging or install flow, also validate:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
agentmemory --help
```

If your change adds or substantially changes a provider, also follow:

- [PROVIDER_CERTIFICATION.md](PROVIDER_CERTIFICATION.md)
- `agentmemory provider-certify <provider-name> --json --run-tests --summary-only`
- `provider-certify-ci --json`

Current certification policy targets:

- `localjson` -> expected `status_code=certified`
- `mem0` -> expected `status_code=certified_with_skips`

If your change affects the shared operation layer or transport surfaces, also validate:

- `tests/test_agentmemory_operations.py`
- `tests/test_agentmemory_operation_adapters.py`
- `tests/test_agentmemory_transport.py`
- `tests/test_agentmemory_api.py`
- `tests/test_agentmemory_mcp_server.py`

## Contribution guidelines

- Keep the default user experience simple and local-first.
- Do not commit `.env`, API keys, local `data/`, or `.venv/`.
- Treat `agentmemory.config.json` as local-only runtime state.
- Treat `status-clients --json`, `doctor-clients --json`, and `doctor-clients` exit codes as public-alpha interfaces.
- Treat provider/client guidance in `doctor`, `status-clients`, `doctor-clients`, and the interactive shell as public-alpha behavior.
- Avoid renaming MCP tools or changing their schemas unless the change is intentional and documented.
- Prefer additive changes over silent behavior changes.
- Keep Windows-specific client integration behavior explicit instead of pretending the whole product has full platform parity.
- Treat provider `capabilities()` and typed provider errors as contract surfaces, not implementation details.
- Treat operation adapters and the shared operation registry as preferred extension points for core memory operations.

## Scope expectations

Good contributions:

- bug fixes
- install and packaging improvements
- clearer diagnostics
- better capability-aware guidance
- safer client integration behavior
- test coverage for public CLI and MCP behavior
- test coverage for shared operation/adapter layers
- documentation improvements

Changes that should be discussed before implementation:

- breaking CLI changes
- MCP tool schema changes
- moving away from OpenRouter-only assumptions
- cross-platform client auto-connect
- authentication or remote-access changes

## Security

- AgentMemory is intended for local use.
- Memory content may contain sensitive user/project data.
- Any change that widens network exposure, changes key handling, or alters local storage behavior should be documented clearly in the PR or changelog entry.
