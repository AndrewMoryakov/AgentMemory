# Start Here

This is the fastest path to evaluate AgentMemory as a public alpha project.

## 1. Understand The Product

Read these first:

- [Why AgentMemory Exists](WHY_AGENTMEMORY.md)
- [Mem0 vs AgentMemory](MEM0_VS_AGENTMEMORY.md)
- [Use Cases](USE_CASES.md)

If you only want the short version:

- use `mem0` directly when one Python app owns memory cleanly
- use `AgentMemory` when memory needs to behave like shared local infrastructure for multiple clients, MCP tools, and scripts

## 2. Try It Quickly

The fastest low-risk path is the built-in `localjson` provider.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
agentmemory configure --provider localjson
agentmemory doctor
agentmemory start-api
python .\examples\http_python_roundtrip.py
```

If you want the main semantic backend, switch to `mem0`:

```powershell
agentmemory configure --provider mem0 --openrouter-api-key "your-openrouter-key"
agentmemory doctor
agentmemory start-api
```

## 3. See Real Scenarios

- [Shared Runtime Demo](../examples/shared-runtime-demo.md)
- [MCP Demo](../examples/mcp-demo.md)
- [Architecture](ARCHITECTURE.md)

## 4. Evaluate Repo Readiness

Useful project-level references:

- [README](../README.md)
- [Contributing](../CONTRIBUTING.md)
- [Roadmap](../ROADMAP.md)
- [Visual Identity](VISUAL_IDENTITY.md)
- [Positioning Assets](POSITIONING.md)
- [Public Repo Settings Checklist](PUBLIC_REPO_SETTINGS.md)

## 5. If You Want To Extend Providers

Read these after you understand the core product:

- [Provider Adapter Rules](./PROVIDER_ADAPTER_RULES.md)
- [Future Memory Providers](future-memory-providers/README.md)
