# Data degradation — prevention and remediation design

Companion to [`SESSION_REVIEW_2026-05-29.md`](SESSION_REVIEW_2026-05-29.md)
and [`AGENT_FRICTION_2026-05-29.md`](AGENT_FRICTION_2026-05-29.md). Those
documents describe the state and the friction. This one explores the
design space of *what we could do about it* — both to prevent future
pools from degrading, and to remediate the current Pool 1 mess that is
already in the database. It does not commit to a strategy; it maps the
options, the tradeoffs, and the cheapest defensive starting points.

Concrete actionable items derived from this discussion live in
[`BACKLOG.md`](BACKLOG.md) as items 46-50. This document is the *why*.

---

## 1. Two distinct problems

There is one phenomenon — "the pool gets less useful over time" — but
two different problems that need different solutions:

**Problem P-prev (prevention).** A pool that does not yet exist, or that
is small enough to still be clean, should not be allowed to drift into
the same condition as Pool 1. Mechanisms here are about discipline,
schema, and feedback loops that keep new writes coherent.

**Problem P-fix (remediation).** Pool 1 (the legal-case pool,
`user_id=topazd2 + agent_id=family_court_child_residence_alimony_case`,
44 records as of 2026-05-29) is already in degraded shape:
- Aggregate records with time-bounded totals and no `stale_after`.
- "Документ 1 v3" implies v1 and v2 are also in the pool, untagged as
  superseded.
- Some records have rich metadata, others have `metadata: {}`.
- Cross-references between records are bare strings, not foreign keys.
- Topically-overlapping records compete for the top of every search.

Pure prevention does nothing for P-fix. Pure remediation buys nothing
for P-prev. Both are needed.

---

## 2. What "degradation" means operationally

From the [`AGENT_FRICTION`](AGENT_FRICTION_2026-05-29.md) analysis, six
modes:

1. **Stale aggregates** — time-bounded totals become wrong as new data
   arrives; agents cite them as current.
2. **Version drift** — superseded versions live alongside current ones;
   agents have to guess which is canonical.
3. **Inconsistent metadata** — some records filterable, others not;
   queries silently miss the untagged ones.
4. **Semantic noise** — multiple records with the same topic mean
   search top-K is filled with near-duplicates; useful diversity falls
   off the bottom of the page.
5. **Cross-reference rot** — string references to other records break
   silently when the target is renamed or deleted.
6. **Convention drift** — different ways of using the same fields
   accumulate over time; the pool stops having a coherent shape.

The operational harm: more tokens consumed per query, longer latency,
higher hallucination risk, less determinism, and zero feedback signal
when any of this gets worse.

---

## 3. Prevention mechanisms — the design space

Five categories, organised by where the mechanism lives.

### 3.1 Schema-level — force the data to have a shape

| Mechanism | Cost | Effect | Limit |
|---|---|---|---|
| Metadata convention in agent system prompt (`kind`, `event_date`, `case_id`, `stale_after`) | 0 code, 10 min | High, *if the agent keeps to it* | Soft discipline only |
| Runtime validation that certain metadata fields are present, per-`agent_id` | ~2 h code | High and hard | Rigid; breaks if convention evolves; blocks legitimate experimentation |
| `memory_type` promoted to first-class enum filter (backlog #38) | ~1 h code | Medium — gives structural splits in queries | Needs vocabulary chosen upfront |
| `metadata.stale_after` on aggregate-shaped records | 0 code (convention) | High *with* read-time honour | Needs caller discipline + read-time support |
| `metadata.supersedes: <memory_id>` lineage | 0 code (convention) | Medium — explicit version chain | Needs read-time honour and auto-archive on supersedes |

**Tradeoff frame:** the soft-discipline path (convention in prompt) is
free but only works as long as the agent stays disciplined. The
hard-validation path (runtime rejection) is robust but rigid — it
breaks when the convention needs to evolve, and it punishes
experimentation. For early-stage use, soft discipline plus read-time
honour is usually right; hard validation only when the convention has
proven stable over months of use.

### 3.2 Behavior-level — bias the system toward update vs. add

| Mechanism | Cost | Effect | Risk |
|---|---|---|---|
| Pre-write similarity check ("there is already a record like this — update it instead?") | ~3 h code | Medium-high — prevents duplicate creation | Extra round-trip; can also wrongly merge genuinely different things |
| Auto-archive on `supersedes` (when a write carries `metadata.supersedes: <id>`, mark the target `archived: true`) | ~1 h code | Targeted | Low — explicit signal from caller |
| Sweeper for stale aggregates (records with `stale_after` in the past get auto-archived with `archived_reason: ttl_aggregate_stale`) | ~2 h code | Medium | Needs the convention to be honored at write |

**Tradeoff frame:** every "bias toward update" mechanism is also a
mechanism for accidental data loss. The safer ones are *suggestive*
(surface a similar record to the caller and let them decide) rather
than *coercive* (auto-merge or auto-archive). Suggestive costs API
round-trips; coercive costs trust. For a single-user system the
suggestive form is the default — coercive becomes attractive only if
the human/agent loop is producing visible duplication.

### 3.3 Observability — see degradation before it bites

| Mechanism | Cost | Effect |
|---|---|---|
| `/admin/pool-health` endpoint: total count, growth rate, age distribution, density per scope | ~2 h code | Visibility but no direct fix; pre-requisite to alerts |
| Search quality sampling: for top-N representative queries, track top-K score spread (densely-packed scores = noisy pool) | ~3 h code | Numerical signal of degradation over time |
| Duplicate detection report: scheduled pass that clusters cosine-close records and reports candidates | ~3 h code | Concrete cleanup target |
| **Read-time stale warning**: when reading a record whose `metadata.stale_after` is in the past, emit `stale_warning` on the envelope | ~30 min code | **Directly closes the hallucination class** for aggregates marked with `stale_after` |

**Tradeoff frame:** observability without action is decoration. Every
observability item should answer the question "what does the operator
do when this signal fires?" — if the answer is "I file a backlog item",
the signal is not load-bearing. Read-time stale warning is the
exception: the signal is consumed by the *agent*, not by a human
operator, and changes the answer the agent gives in real time. That
makes it the highest-leverage item in this category.

### 3.4 Workflow-level — change how the agent uses the pool

| Mechanism | Cost to agent | Effect |
|---|---|---|
| Living-summary pattern: one canonical record per topic, updated in place; raw chunks separately | High (retraining) | Very high long-term — keeps the *active* set small |
| Periodic auto-reconcile before synthesis (call `memory_reconcile`, surface conflicts) | Medium (one extra call per synthesis) | Catches contradictions before they reach the user |
| Cite-with-date discipline ("as of 2026-05-27 the figure was X" rather than "the figure is X") | Low (prompt change) | Prevents stale-as-current hallucination at quotation time |

**Tradeoff frame:** workflow-level changes do not require any code in
this repo — they require system-prompt edits in the agent that owns
the pool. That makes them the cheapest *and* the most fragile: free to
land, but they revert silently the moment someone edits the prompt
elsewhere. Pair them with read-time enforcement (3.3) so the system
still protects when the prompt drifts.

### 3.5 Architecture — bigger shifts, defer until proven needed

| Mechanism | Cost | When justified |
|---|---|---|
| Tiered storage (hot working set + cold archive) | High (new layer + classification policy) | Pool grows past ~1000 records *and* search latency or noise are visibly hurting |
| Knowledge graph / structured DB next to mem0 for relation-heavy facts | Very high (separate system to operate) | When the dominant query is "give me everything related to X" and flat-text retrieval can no longer answer it |
| Switch to a different provider with native versioning | Very high (provider re-implementation) | When `mem0` becomes a visible bottleneck (not when its design is theoretically imperfect) |

**Tradeoff frame:** every architectural item here is a different
product, not a feature. The signal that justifies one is recurring
operational pain that the cheaper mechanisms (3.1-3.4) could not
contain. We do not have that signal today.

---

## 4. Remediation — what to do about the current Pool 1 mess

Three options, in increasing order of disruption.

### 4.1 Read-only annotation pass (least invasive)

Pass over the 44 records, write nothing destructive, only tag:

- Find aggregate-shaped records (heuristic: text contains "ИТОГО",
  "совокупно", "за весь период", or `metadata.format` includes
  "aggregate"). For each: `memory_update` adding
  `metadata.stale_after = <date parsed from text "по состоянию на …">`.
- Find superseded versions (e.g. "Документ 1 v1" while a v3 exists in
  the pool). For each: `memory_update` with `metadata.archived: true`
  and `metadata.archived_reason: "superseded_by_v3"`.
- Backfill `metadata.case_id` on records where it is missing.

**Time:** ~30 minutes of disciplined agent work, or a one-off script.

**Effect:** the cheapest move that makes 3.3's read-time stale warning
actually load-bearing for the current pool. No information is lost.

### 4.2 Living-summary refactor (more invasive)

Of the 44 chunks, perhaps 5-7 distinct *operational topics* are what
the agent actually queries against in practice: current child residence
status, total alimony to date, child-related direct expenses, document
state in court, episode timeline. Create 5-7 canonical *living* records
for those topics. Archive the remaining 37-39 chunks with
`metadata.archived: true` so they fall out of the active search space
but remain available via `include_archived: true` admin queries.

**Time:** ~2-3 hours of agent work to identify topics, draft canonical
records, classify the existing chunks.

**Effect:** very high — search becomes precise, and the agent has a
canonical "current state" for each topic.

**Tradeoff:** detail is harder to retrieve. If tomorrow we need the
exact Telegram message id from 11.05.2026, it now lives in an
archived chunk that the default search will not surface. Compensable
by either keeping the chunks discoverable through a structural filter
or by re-introducing the most frequently re-queried details into the
living summaries on demand.

### 4.3 Extract raw chunks out of memory entirely (most disruptive)

The radical position: "memory should not be a document store". Move
the raw chunks (Telegram transcripts, bank statement analyses, evidence
notes) into a different store — a project-scoped SQLite, a folder of
git-tracked markdown, anything. Keep in `agentmemory` only the
derived current state (the 5-7 living summaries from 4.2).

**Time:** a day or more of work, including the migration script and
the workflow change in the legal-case agent.

**Effect:** ideal use of mem0 (small set of living facts) plus
unconstrained store for the raw corpus.

**Tradeoff:** double the systems to operate. Worth doing only if the
living-summary refactor itself has demonstrated value over weeks of
use.

---

## 5. Cost vs return summary

| Item | Cost | Return | Risk | Recommended when |
|---|---|---|---|---|
| Read-time `stale_warning` (3.3 / backlog #46) | ~30 min | High direct protection from hallucination | Low | Now |
| Pool 1 read-only annotation pass (4.1) | ~30 min | High — closes the 297 580 ₽ class | None (no destructive writes) | Now |
| Metadata convention in legal-agent prompt (3.1 first row) | 10 min | Discipline for future writes in Pool 1 | None | Now |
| Pre-write similarity check (3.2 / backlog #47) | ~3 h | Medium — reduces duplication | Round-trip cost | When duplication becomes visible |
| Pool health endpoint (3.3 / backlog #48) | ~2 h | Observability | None | When more than one operator |
| Duplicate detection report (3.3 / backlog #49) | ~3 h | Cleanup target | None | Before 4.2 |
| Living-summary refactor (4.2 / backlog #50) | ~3 h agent time | Very high long-term | Detail less discoverable | When Pool 1 grows past ~100 records, or search noise is visible |
| Extract raw chunks (4.3) | day+ | Ideal architecture | Double the systems | After 4.2 has been used for weeks |
| Tiered storage, KG, provider switch (3.5) | days-weeks | Strategic | Massive rework | Only when cheaper mechanisms have measurably failed |

---

## 6. Recommended sequence

**Step 1 (today, ~1 hour total):**
- Code: read-time `stale_warning` on every read path (backlog #46).
  Records whose `metadata.stale_after` is in the past come back with
  `stale_warning: { stale_since: <iso>, days_overdue: N }` in the
  envelope. Read path is non-destructive: nothing is filtered, just
  tagged.
- Data: Pool 1 read-only annotation pass (4.1). Tag aggregates with
  `stale_after`. The read-time warning above immediately starts
  protecting them.
- Prompt: add the metadata convention paragraph to the legal-case
  agent's system prompt.

After Step 1: the immediate hallucination class for aggregates is
contained, and new writes from the legal-case agent come in with the
convention.

**Step 2 (next 1-2 weeks):**
- Backlog #43 (sanity-guard TTL values when enabled) — defense in depth
  if TTL ever opts in.
- Watch Pool 1 growth. If it stays under ~70 records and the
  stale-warning rate stays low, Step 3 is not needed yet.

**Step 3 (when Pool 1 grows past ~100 records, *or* the agent reports
that search misses important context):**
- Living-summary refactor (4.2, backlog #50).
- Duplicate detection report (3.3, backlog #49) for targeted cleanup.

**Step 4 (only when Step 3 has been in use for weeks and clearly
helping):**
- Consider 4.3 (extract raw chunks) and any of 3.5 (architecture).

---

## 7. What we deliberately do NOT do, and why

- **Runtime hard validation of metadata fields.** Too rigid for a
  pre-product workflow. Re-evaluate after the convention has been
  stable in the system prompt for several months.
- **Pre-write similarity check as a default.** Doubles every write,
  for a duplication problem that is not yet measured. Backlog item
  exists (#47); activation deferred until duplication is visible.
- **Pool health observability without alerts.** Observation without
  action is decoration. Build it the day there is an alerting target.
- **Auto-merge of cosine-close records.** Coercive deduplication
  trades visible mess for invisible data loss — the wrong trade for
  this domain (legal context).
- **Pull raw chunks out of memory now.** The cheaper mechanisms
  (4.1, then 4.2) close most of the harm at one tenth the workflow
  disruption. Only consider 4.3 after they have failed to scale.
- **Switch storage backend, build a KG, or extend mem0.** These are
  product-level decisions. Defer until there is recurring operational
  pain that the cheaper mechanisms cannot contain.

---

## 8. Cross-references

- Operator-side context: [`SESSION_REVIEW_2026-05-29.md`](SESSION_REVIEW_2026-05-29.md)
  §2 P1 (legal-case pool fragility), §3 F1 (search degradation as the
  pool grows).
- Agent-side context: [`AGENT_FRICTION_2026-05-29.md`](AGENT_FRICTION_2026-05-29.md)
  §2 (retrieval friction), §6 (hallucination from stale aggregates),
  §8 (cost summary), §9 (compensations the agent must make).
- Actionable PR-sized items derived from this design space:
  [`BACKLOG.md`](BACKLOG.md) items 46-50.
- Already closed in code: item 42 (TTL off by default — commit
  `c89cc6f`) closes one specific data-loss class; this document
  addresses a different class (slow signal-to-noise erosion rather
  than terminal deletion).
