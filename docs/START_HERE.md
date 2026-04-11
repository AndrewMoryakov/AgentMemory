# Start Here

This is the fastest path to evaluate AgentMemory as a public alpha project.

## 1. Fastest Path To First Success

Do this first. Do not start with `mem0`.

Use the built-in `localjson` provider to prove the runtime works end to end without external API keys or semantic-provider setup.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\agentmemory.exe configure --provider localjson
.\.venv\Scripts\agentmemory.exe doctor
.\.venv\Scripts\agentmemory.exe start-api
.\.venv\Scripts\python.exe .\examples\http_python_roundtrip.py
.\.venv\Scripts\python.exe -m agentmemory.ops_cli list --user-id examples-http-roundtrip --limit 5
```

What success looks like:

- `doctor` reports no blocking errors
- `start-api` prints the local API URL
- the roundtrip script creates a memory and prints list/search results
- the final `list` command shows at least one memory for `examples-http-roundtrip`

When you are done:

```powershell
.\.venv\Scripts\agentmemory.exe stop-api
```

This is the canonical onboarding story:

- write through HTTP
- read back through CLI
- confirm one shared runtime serves both surfaces

Related demo:

- [Shared Runtime Demo](../examples/shared-runtime-demo.md)

## 2. Understand The Product

Read these first:

- [Why AgentMemory Exists](WHY_AGENTMEMORY.md)
- [Mem0 vs AgentMemory](MEM0_VS_AGENTMEMORY.md)
- [What AgentMemory Actually Adds](WHAT_AGENTMEMORY_ACTUALLY_ADDS.md)
- [Use Cases](USE_CASES.md)

If you only want the short version:

- use `mem0` directly when one Python app owns memory cleanly
- use `AgentMemory` when memory needs to behave like shared local infrastructure for multiple clients, MCP tools, and scripts

## 3. Switch To Mem0 Only After Localjson Works

If the `localjson` path succeeded and you want the main semantic backend, switch to `mem0`:

```powershell
.\.venv\Scripts\agentmemory.exe configure --provider mem0 --openrouter-api-key "your-openrouter-key"
.\.venv\Scripts\agentmemory.exe doctor
.\.venv\Scripts\agentmemory.exe start-api
.\.venv\Scripts\python.exe .\examples\http_python_roundtrip.py
```

What success looks like:

- `doctor` confirms the configured runtime is usable
- `start-api` starts cleanly with the configured provider
- the roundtrip script still works through the same client-facing flow

If `mem0` fails, go back to `localjson` and confirm the runtime path still works there. The first evaluation should prove the runtime first and the semantic provider second.

## 4. See Real Scenarios

- [Shared Runtime Demo](../examples/shared-runtime-demo.md)
- [MCP Demo](../examples/mcp-demo.md)
- [Architecture](ARCHITECTURE.md)

## 5. Quick Troubleshooting

- If `agentmemory` is not found, use the explicit `.venv` command paths shown above instead of relying on shell activation.
- If the API fails to start, rerun `.\.venv\Scripts\agentmemory.exe doctor` and read the blocking errors first.
- If the API port is already in use, wait for `start-api` to print the selected URL before running the roundtrip script.
- If `mem0` fails, do not debug both the runtime and provider at once. Reconfirm the `localjson` path first.

## 6. Evaluate Repo Readiness

Useful project-level references:

- [README](../README.md)
- [Contributing](../CONTRIBUTING.md)
- [Roadmap](../ROADMAP.md)
- [Visual Identity](VISUAL_IDENTITY.md)
- [Positioning Assets](POSITIONING.md)
- [Public Repo Settings Checklist](PUBLIC_REPO_SETTINGS.md)

## 7. If You Want To Extend Providers

Read these after you understand the core product:

- [Provider Adapter Rules](./PROVIDER_ADAPTER_RULES.md)
- [Future Memory Providers](future-memory-providers/README.md)
