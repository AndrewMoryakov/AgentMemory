# Agent friction — how the current memory state impedes effective use

Companion to [`SESSION_REVIEW_2026-05-29.md`](SESSION_REVIEW_2026-05-29.md).
That document looks at the system from the operator's seat — what is
broken, what is brewing, what to fix. This document looks at it from
the *agent's* seat — what happens to an LLM agent that has to actually
use this memory to do work, and where the gap between "memory holds
data" and "agent can act on data" actually bites.

The running example is the production legal-case pool (`user_id=topazd2`
+ `agent_id=family_court_child_residence_alimony_case`, 44 records as
of 2026-05-29). That pool is the only large body of real working data
we have, and it exhibits every friction mode listed below.

---

## 1. The expectation–contract gap

An agent using long-term memory implicitly assumes:

- The store **remembers what was told** — verbatim, without losing detail.
- The store **does not lie about current state** — what comes back is
  current truth, not legacy.
- The store **does not duplicate context** — one answer per topic.
- The store **is internally consistent** — does not contradict itself.
- The store **understands relationships between records** — order,
  hierarchy, supersession.

The actual mem0 + AgentMemory contract:

- Stores what you send, **but may rewrite via LLM** when `infer=true`
  (silent compression of details).
- **Has no notion of time**: a record written in December containing
  totals that were valid through November is returned in May with
  the same similarity score as a record written yesterday.
- Returns **top-K semantically similar** results — not "the right
  ones".
- **No consistency model**: two contradictory facts can coexist;
  neither flagged.
- Relationships exist only as **text inside records** — to the engine
  they are strings, not foreign keys.

Every friction below is a consequence of this gap.

---

## 2. Retrieval friction — "find me what was about April"

The agent issues `memory_search(query="расходы за апрель",
user_id="topazd2", limit=10)`.

It gets back:

- April monthly report (score 0.85) — wanted.
- March monthly report (score 0.79) — same template, irrelevant.
- Period-wide aggregate as of 2026-05-27 (score 0.77) — covers April
  but **may be stale** if there is new data after 2026-05-27.
- Thematic context note on visit logistics (score 0.72) — mentions
  April episodes, but it's about a different question.
- Six more records with comparable scores.

What the agent must do to use this answer:

1. Read all 10 records.
2. Recognize that the March report is not what was asked for (no
   structural filter exists for "only April").
3. Recognize that the aggregate may be **out of date** — by reading
   the "по состоянию на 27.05" wording inside the text, not by any
   metadata field.
4. Recognize that the thematic note is about logistics, not finance.
5. Decide which of the 10 to actually use and which to discard.

The cost:

- **2-5× more tokens** in working context (read 10, used 3).
- **30-90 seconds of extra latency** for reading and filtering.
- **High hallucination risk**: cite a stale aggregate as if it were
  current.

What the agent **cannot do at all** today:

- Ask "only monthly reports, please" — no `metadata.kind` filter,
  because metadata is inconsistent across records.
- Ask "records where event_date is in April" — that date is buried
  in text; `created_at` is when the record was *written*, not when
  the event happened.
- Tell what fell off the top-10 — the reranker is opaque.

---

## 3. Storage friction — "record a new transfer on 28.05"

The agent has new data. It must decide:

- `add` a new record → ends up as a near-duplicate of the April
  report (semantic noise in search forever after).
- `update` an existing record → which one? The April report? The
  period-wide aggregate? Both?
- If both, the agent must **know** both record ids — meaning a
  `search` to find them, a `get` on each to read structure, then
  two separate `update` calls to keep them in sync.

If the agent forgets to also update the aggregate, the next read
will quote the old total as current truth.

Cost: **one user-level operation becomes 3-5 API calls**, each of
which is a place to leave the store in a partially-updated state.

What does not exist:

- Transactional "update April and the aggregate atomically".
- "This new record **supersedes** that aggregate" semantics.
- A signal "you have an aggregate whose `stale_after` is in the
  past — update or archive it".

---

## 4. Update friction — "change the nanny's name in the April report"

The agent calls `memory_update(memory_id="...", data="new text")`.

What happens:

- Text is replaced. Good.
- **Metadata is also replaced** if the agent passes a metadata
  argument — so all previously-set `case`, `chunk`, `source`,
  `verified_until` fields disappear unless the agent re-sends them.
- The previous version of the record **vanishes without trace** —
  no audit log, no "what it was before".

The careful agent must:

1. `get` the record first.
2. Read its metadata.
3. Merge any new metadata with the existing fields.
4. (Optionally) preserve the previous text somewhere — in
   `metadata.previous_text`, or as a separate record.
5. `update` with the merged metadata.

The lazy agent that just writes `update(id, new_text)` silently
loses all structural metadata. The pool already shows records with
`metadata: {}` next to records with rich metadata — this is one
plausible explanation.

---

## 5. Synthesis friction — "summarise the case as of today"

The agent wants to read the whole pool, synthesise current state.

What is available: 44 records, no graph of relationships between
them, no timeline.

What the agent has to do:

1. `memory_list(user_id="topazd2", agent_id="family_court...")` —
   pull all 44.
2. Read all 44 — large slice of working context.
3. Reconstruct chronological order **from dates inside the text**
   (`created_at` is when it was written, not when the event happened).
4. Find contradictions — alone, mem0 does not surface them.
   `memory_reconcile` exists (item 6 in the closed set of the
   backlog) but must be invoked explicitly.
5. Decide which record is "current" for any given fact — last
   write wins? aggregate vs detail? The agent must guess.
6. Skip superseded versions — but they are not marked
   `archived: true`; the agent must infer supersession from text
   ("Документ 1 v3" implies v1 and v2 are somewhere too).

Cost: **50,000-100,000 tokens** to read the pool, 30-90 seconds
of latency, and a **non-deterministic result** — running the same
synthesis twice can give different summaries because of reranker
variance and prompt-level prioritisation drift.

---

## 6. Hallucination risk — "how much in total did the father pay"

The worst scenario, because it is silent.

A record dated 2026-05-27 says **"ИТОГО: 297 580 руб."** as the
aggregate for the period through 2026-05-27.

It is now 2026-05-29. If a transfer happened on 2026-05-28, that
total is wrong. But:

- The record is not marked `stale: true`.
- There is no `stale_after: 2026-05-27` field.
- There is no link to "source: bank statement X, accurate through Y".
- Semantic search for "итого алиментов" will return it as the top hit.

The agent **will quote 297,580 руб. as current truth**. This is:

- Not the agent's fault — it has no signal that the record is stale.
- Not the system's fault — it stores what it was given.
- A **workflow gap**: between "is stored" and "is current" there
  is no representational distinction in the data.

In a legal context, that gap can cost real money.

---

## 7. Internal contradictions

The pool contains, for the same event:

- Record A: "the father offers the mother to spend time with the
  child" (cooperative framing).
- Record B somewhere: "the father refuses to hand the child over"
  (adversarial framing).

These two can coexist in memory without anything flagging the
conflict. `memory_reconcile` can detect such pairs, but:

- It does not run automatically.
- The agent has to **know** to run it.
- The output is a list of pairs, not a resolution.

An agent doing synthesis can cite **both** records as facts, even
though they describe the same underlying event with opposite spin.

---

## 8. Summary table

| Agent workflow | What impedes | Cost vs. clean baseline | Error risk |
|---|---|---|---|
| Retrieve | aggregate staleness, semantic noise, no structural filter | 2-5× tokens, 30-90s latency | High (stale quote) |
| Store | add/update ambiguity, no supersession semantics | 3-5× API calls | Medium (partial state) |
| Update | replace-not-merge, no audit | 2× API calls if careful, data loss if not | High (metadata loss) |
| Synthesise | no graph, no timeline, conflicts not surfaced | 50-100k tokens per pool | High (inconsistent output) |
| Cite as fact | no freshness signal on aggregates | none | **Critical** (silent hallucination) |

---

## 9. What this implies for agent design

To be reliable against data shaped like Pool 1, the agent has to
**compensate for what the system does not provide**:

1. **Read-before-write for updates** — always `get` → merge metadata
   → `update`. Never pass metadata blindly.
2. **Freshness check in synthesis** — for any aggregate-shaped
   record, parse "as of <date>" out of the text and compare against
   today before quoting.
3. **Cite with the date** — "as of 2026-05-27 the figure was 297,580"
   instead of "the figure is 297,580".
4. **Periodic reconcile** — run `memory_reconcile` before synthesis,
   surface conflicts to the user instead of merging them.
5. **Conservative trust** — never use a single occurrence as a
   citable fact; cross-check across multiple records.

These workarounds **shift load from the system to the agent**.
The proposed `stale_after` metadata convention plus backlog items
#36-#41 make this load smaller, but they do not remove it as long
as the pool is structurally "document store implemented through
flat memory".

---

## 10. One-paragraph summary

Memory for the agent today is a *very good search box over a flat
collection of notes*. It does not know what is currently true, what
is stale, what contradicts what, what came before what. The agent
must derive every one of those properties **itself**, from the text
of the records — but the text is written for human or LLM
*reading*, not for machine *reasoning*. This works at 44 records and
with one disciplined agent. At 200+ records with variable
discipline, it starts to degrade **silently** — there is no point
in time at which it visibly "breaks" and triggers a fix; the answers
just slowly become more often wrong.
