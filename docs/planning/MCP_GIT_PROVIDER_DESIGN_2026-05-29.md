# MCP-over-git provider — landscape analysis and design direction

Companion to the [data-degradation design](DATA_DEGRADATION_DESIGN_2026-05-29.md)
document. That document concluded that "mem0 as document store" is an
architectural mismatch for use cases like the production legal-case
pool, and that the right home for long-form structured documents is a
document store rather than a vector-fact store. This document answers
the natural follow-up: what would such a document store look like as an
MCP-accessible provider, and what are the options.

The recommendation it lands on — extend AgentMemory with a document-
oriented provider backed by git + markdown — is also captured as a
strategic direction in [ROADMAP.md](ROADMAP.md) under "Provider
Direction: Document-Oriented Backends".

---

## 1. The question

For hosted MCP agents (Claude.ai web custom connectors, ChatGPT
custom connectors, Claude Desktop, plus local Claude Code), what
existing infrastructure could play the role of a "write a long-form
document, retrieve it later by id or by structural filter without
relying on semantic search" store, and how does it compare to building
a new provider into AgentMemory?

The constraints set by hosted agents are tighter than they look:

- No shell access — hosted agents cannot execute `git`, `grep`, or
  any filesystem command directly.
- No filesystem access — hosted agents cannot read or write files.
- Streamable HTTP MCP transport only — Claude.ai's connector dialog
  accepts a URL; ChatGPT custom connectors do the same. stdio MCP
  servers are not directly addressable from a hosted agent without
  an HTTP bridge.

These constraints rule out "just put it in a git repo and let the agent
shell into it" as a viable path for hosted use.

---

## 2. Existing MCP-server landscape relevant to git

### 2.1 Official servers from Anthropic (`modelcontextprotocol/servers`)

| Server | Surface | Transport |
|---|---|---|
| `mcp-server-git` | Generic git ops: `git_log`, `git_diff`, `git_status`, `git_show`, `git_add`, `git_commit` | stdio |
| `mcp-server-filesystem` | `read_file`, `write_file`, `list_directory`, `move_file` | stdio |
| `mcp-server-github` | GitHub REST API wrapper: `create_or_update_file`, `search_code`, `get_file_contents`, plus issues / PRs | stdio |
| `mcp-server-gitlab` | Equivalent surface for GitLab projects | stdio |

These cover the "agent reaches an existing git repo" use case for stdio
clients. They do not implement document semantics — they expose git
primitives, leaving the agent to compose them. Writing one document in
this model takes three calls: `write_file` -> `git_add` -> `git_commit`.

### 2.2 Community servers

The community space includes wrappers around Gitea, various Obsidian
vaults (often git-synced), and several knowledge-base patterns. Maturity
varies, and documentation about HTTP-transport support is uneven.

### 2.3 The transport gap

All four official servers above use stdio transport. Stdio MCP servers
are spawned as child processes by the MCP client and communicate over
the child's stdin/stdout. This works for:

- Claude Code CLI (`claude mcp add … --transport stdio …`)
- Claude Desktop (`claude_desktop_config.json` -> `command` + `args`)

It does **not** work for hosted agents whose connector dialog only
accepts an HTTP URL. To use any of these stdio servers from Claude.ai
web or ChatGPT custom connectors, an intermediate stdio-to-HTTP bridge
(such as `mcp-proxy`) must be self-hosted, which adds operational
surface and obscures the failure modes.

---

## 3. Realistic scenarios for "MCP over git"

### Scenario A — local agents only (Claude Code, Claude Desktop)

`mcp-server-git` + `mcp-server-filesystem` registered as stdio MCP
servers covers this. Works today. Setup cost is essentially zero
(`claude mcp add` calls).

Trade-offs: generic git surface, three-call writes, no document
semantics, no hosted-agent reach.

### Scenario B — hosted agents (Claude.ai web, ChatGPT)

No off-the-shelf solution combines all of (a) HTTP transport,
(b) self-hosted privacy, and (c) document semantics. The realistic
paths are:

**B1 — GitHub MCP + stdio-to-HTTP bridge + private repo.**

Write becomes one logical call (`github_create_or_update_file` does
write + commit + push in one). Read becomes one call
(`github_get_file_contents`). The bridge translates between the
hosted agent's HTTP transport and the stdio MCP server.

Trade-off: the data lives on GitHub. For non-sensitive projects this
is acceptable. For a legal case, putting documents on a third party's
servers is a privacy and discovery-risk concern.

**B2 — Self-hosted Gitea + community Gitea MCP + bridge.**

Replaces GitHub with a self-hosted git forge running on the same VPS.
Keeps data local. Adds Gitea as an extra service to operate, plus the
maturity question for the community MCP layer.

**B3 — Custom HTTP-MCP server built from scratch.**

Roughly a day of focused work for a small surface (`document_add`,
`document_get`, `document_search`, `document_list`, `document_supersede`).
Backend is markdown-in-git on the same VPS. Natively serves Streamable
HTTP MCP, so hosted agents reach it directly. Privacy preserved.

Trade-off: stands alone — duplicates infrastructure (auth, backup,
deploy) that AgentMemory already has.

**B4 — Add a document provider into AgentMemory.**

Same surface and backend as B3, but implemented as a new
`BaseMemoryProvider` subclass inside the existing AgentMemory runtime.

What this inherits for free:

- Streamable HTTP MCP transport (already serves Claude.ai
  connectors today).
- OAuth 2.1 + DCR + refresh tokens.
- Bearer token fallback.
- Backup chain (server cron -> off-host pull, both already in
  production).
- Traefik route, TLS termination, healthcheck.
- Single MCP server to register with the hosted agent.
- Same admin tooling, metrics, monitoring as the existing providers.

Trade-off: most coupled to this codebase. Provider boundary needs
to be respected so document semantics do not leak back into the
fact-store providers.

### Scenario C — both local and hosted from one backend

The same git repository served via two surfaces simultaneously — stdio
for local Claude Code, HTTP for hosted Claude.ai. Achievable through
B3 or B4 (one core, two transports) but adds wiring complexity.

---

## 4. Comparison of paths

| Path | Ready today | Hosted agents reach | Privacy | Setup cost | Document semantics |
|---|---|---|---|---|---|
| `mcp-server-git` + `mcp-server-filesystem` (stdio only) | yes | no (without bridge) | local | near zero | no — generic git ops |
| same + `mcp-proxy` bridge | yes (bridge exists) | yes | local | low | no — generic git ops |
| `mcp-server-github` + bridge | yes (bridge exists) | yes | data on GitHub | low | partial — through GitHub API |
| Self-hosted Gitea MCP | community implementations exist | yes (with bridge) | local | medium (Gitea + bridge) | partial — generic git ops |
| Custom HTTP-MCP (B3) | no — must build | yes natively | local | ~day | tailored to use case |
| AgentMemory document provider (B4) | no — must build | yes natively | local | ~day | tailored to use case |

The fastest "ready today" path that also reaches hosted agents is the
GitHub MCP plus a stdio-to-HTTP bridge with a private repo (B1). The
privacy trade-off makes it unsuitable for the production legal-case
data on this host.

The two paths that satisfy all three constraints — HTTP transport,
self-hosted privacy, tailored document semantics — both require
building. B3 stands alone, B4 lives inside AgentMemory and reuses its
infrastructure.

---

## 5. Agent-side transparency of the B4 choice

A property worth naming explicitly: from the hosted agent's
perspective, choosing B4 over a separate document service is
invisible.

The agent already speaks to AgentMemory at
`https://agentmemorytool.duckdns.org/mcp` with a Bearer / OAuth token.
After adding the document provider:

- The MCP URL stays the same.
- The OAuth flow stays the same.
- The connector configuration in Claude.ai stays the same — no
  re-authorisation required.
- The provider's storage internals (git operations, markdown frontmatter,
  file paths, commit messages) are not exposed to the agent in any
  way.

The only change visible to the agent is that the next `tools/list`
response carries additional tools — `document_add`, `document_get`,
`document_search`, `document_list`, and so on — alongside the existing
`memory_*` tools. Each new tool's description guides the agent on when
to use it ("for long-form structured documents with versioning, prefer
`document_*`; for short atomic facts, prefer `memory_*`"). A modern
LLM agent typically chooses correctly from the tool descriptions alone;
a one-paragraph nudge in the agent's system prompt makes it bulletproof.

This is exactly the same provider-substitution property that AgentMemory
already supports for `mem0`, `localjson`, `claude_memory`, and
`mempalace`: providers can be swapped or stacked without changing how
the agent reaches the MCP server.

---

## 6. Recommended direction

**Adopt B4 — add a document-oriented provider into AgentMemory backed by
markdown files in a git repository.**

Rationale, in order of weight:

1. **Operational reuse.** AgentMemory already runs a hardened
   Streamable HTTP MCP server with OAuth 2.1 + DCR + refresh, with
   persistent token storage, with a two-leg backup chain (server cron
   plus off-host pull), with Traefik ingress, with healthcheck, and
   with CI. Building B3 as a standalone service would duplicate every
   one of those concerns.

2. **Single connector surface for the agent.** Claude.ai (and any
   other hosted agent) configures one MCP connector. Discovery,
   authorisation, and audit happen against one endpoint. Adding a
   second MCP server would mean a second connector to authorise, a
   second URL to remember, and a second piece of infrastructure to
   monitor — for no agent-side benefit.

3. **Provider-pattern fit.** AgentMemory's provider architecture is
   already provider-generic (see `BaseMemoryProvider`,
   `ProviderContract`, `ProviderCapabilities`). Adding a document
   provider follows the same pattern that `mem0`, `localjson`,
   `claude_memory`, and `mempalace` already follow. The cost is
   proportional to those existing providers, not to a from-scratch
   service.

4. **Backend correctness for legal-case data.** Markdown in git gives
   audit trail via commits, diffs via `git diff`, version recovery
   via `git checkout`, branch-based what-if exploration, and export
   to PDF via `pandoc` — all the things document-oriented work
   benefits from, and none of which mem0 can provide regardless of
   how careful the convention is.

5. **Coexistence with existing fact storage.** The fact-store role
   (small atomic semantic facts, retrieved by similarity) is what
   mem0 is good at and should keep doing. The document-store role
   (long-form structured documents, retrieved by id or by structural
   filter, versioned) is a separate role. Hosting both in the same
   runtime under distinct providers is the cleanest separation —
   neither role contaminates the other, both are reachable through
   one MCP surface.

---

## 7. Rough scope of work

A first-cut implementation of the document provider would land in a
single PR plus a short follow-up for ergonomics. Approximate scope:

- New `agentmemory/providers/git_document.py` implementing
  `BaseMemoryProvider` with document semantics. Storage layout:
  `<runtime_dir>/documents/<case_id>/<kind>/<doc_id>.md` with YAML
  frontmatter for metadata. Backed by a git repository initialised
  on first use; commits attributed to `agentmemory-bot <bot@local>`
  unless overridden.
- Provider contract extension to surface document-specific capability
  flags: `supports_versioning`, `supports_supersedes`,
  `supports_typed_references`.
- Operations registry entries for `document_add`, `document_get`,
  `document_search` (full-text via `git grep` or a small inverted
  index helper), `document_list`, `document_supersede`,
  `document_get_versions`.
- MCP tool descriptions tuned so a hosted agent reading `tools/list`
  picks correctly between `memory_*` and `document_*`.
- A short docs page in `docs/USE_CASES.md` describing when to use
  documents vs. facts.
- Tests covering: add roundtrip, get-by-id, list-with-filter,
  supersedes chain, version retrieval, structural search.
- A migration helper script that walks an existing mem0 scope, picks
  records that look like documents (heuristics: text length, presence
  of internal headers), and moves them into the document provider —
  optional, run-once.

The work is provider-shaped and matches the existing pattern. It does
not require any change to the runtime core, the OAuth layer, or the
transport layer.

---

## 8. Cross-references

- The data-degradation context that motivates this design:
  [`DATA_DEGRADATION_DESIGN_2026-05-29.md`](DATA_DEGRADATION_DESIGN_2026-05-29.md)
  §3.5 (architectural shifts deferred until proven needed) and §4.3
  (extracting raw chunks from memory entirely).
- The agent-side friction this would relieve:
  [`AGENT_FRICTION_2026-05-29.md`](AGENT_FRICTION_2026-05-29.md) §2-§5
  (retrieve / store / update / synthesise friction modes).
- The strategic-direction entry in the project roadmap:
  [`ROADMAP.md`](ROADMAP.md) -> "Provider Direction: Document-Oriented
  Backends".
