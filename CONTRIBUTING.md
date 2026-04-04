# Contributing

Thanks for contributing to AgentMemory.

This project is currently a `public alpha` with a cross-platform runtime and a Windows-first client integration workflow, so contributions should prioritize clarity, stability, and local operability over broad abstraction.

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

## Contribution guidelines

- Keep the default user experience simple and local-first.
- Do not commit `.env`, API keys, local `data/`, or `.venv/`.
- Treat `agentmemory.config.json` as local-only runtime state.
- Treat `status-clients --json`, `doctor-clients --json`, and `doctor-clients` exit codes as public-alpha interfaces.
- Avoid renaming MCP tools or changing their schemas unless the change is intentional and documented.
- Prefer additive changes over silent behavior changes.
- Keep Windows-specific client integration behavior explicit instead of pretending the whole product has full platform parity.

## Scope expectations

Good contributions:

- bug fixes
- install and packaging improvements
- clearer diagnostics
- safer client integration behavior
- test coverage for public CLI and MCP behavior
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
