# Phase 07 — Retrieval — **ACCEPTANCE GATE**

**Objective.** OpenViking wired in, the vault indexed, scope resolution working, and a
synthesis subagent that cites or abstains.

**This is the go/no-go checkpoint.** Nothing with write access is built until it passes.

**Preconditions.** Phase 06 gate green.

Read [`08-retrieval.md`](../08-retrieval.md) and
[`03-decisions.md`](../03-decisions.md#d-02--retrieval-openviking) in full first.

---

## Step 0 — The spike, before anything else

Two properties of OpenViking are load-bearing and neither is confirmed by its
documentation at the level of certainty this design needs. **Establish both before writing
integration code.** Timebox: half a day.

**Spike A — scoped recall precision.** Index the synthetic evaluation corpus. Issue a
recall scoped to a single lecture's path. Assert that **no** candidate comes from outside
that scope. If path scoping is advisory rather than a hard boundary, the entire filter
model in D-03 fails and this phase stops.

**Spike B — local embeddings end to end.** Configure OpenViking's embedding provider
against `athena-ml`'s OpenAI-compatible endpoint and confirm, by watching `athena-ml`'s
request log, that **every** embedding call lands there and none leaves the machine. The
provider list supports `local`, `ollama`, and `litellm` with a custom `api_base`; confirm
it on the pinned version rather than trusting the docs.

Record both results in the phase's commit message with the exact version tested. If either
fails, **stop and report** — the fallback is D-19 and that is a decision for the owner, not
an improvisation.

---

## Steps

### 1. Pin and run OpenViking

Add it to `docker/compose.dev.yml` at an **exact released tag**. Never `:latest`, never a
locally built image.

`config/openviking.json` holds its configuration, mounted read-only:

- embedding provider → `http://athena-ml:8082/v1`, local model, dimension matching
- VLM provider → OpenRouter (D-05's noted risk), configured explicitly
- **`evolution.enabled = false`** — auto-capture and agent evolution are off (I-02,
  [`08-retrieval.md`](../08-retrieval.md#what-athena-keeps-out-of-openviking))

`athena-ml` gains an OpenAI-compatible `/v1/embeddings` route in this phase. That is the
only change OpenViking forces on it.

### 2. `RetrievalProvider` interface

`src/athena/retrieval/provider.py` — the protocol from
[`08-retrieval.md`](../08-retrieval.md#the-fallback): `index`, `remove`, `recall`, `read`.

Write the interface first and `OpenVikingProvider` against it. The indirection is the
reversal path for D-02 and it costs one file.

`FakeRetrievalProvider` in `tests/fakes/` implements the same protocol with real
path-scope semantics, so scope logic is testable without running the service.

### 3. Date resolution

`src/athena/retrieval/dates.py` — resolve relative expressions ("last Tuesday's lecture",
"the lecture before the midterm") against the owner's timezone and the course meeting
schedule in `_course.md`.

Exposed as a small tool for the orchestrator to call, but the arithmetic is deterministic
Python (I-11). The model supplies the phrase; it does not compute the date.

### 4. Scope resolution

`src/athena/retrieval/scopes.py`, per
[`08-retrieval.md`](../08-retrieval.md#scope-resolution).

The rule that matters: **an unresolvable filter returns an error, never an empty scope
list.** Empty must not fall through to "search everything" — silently widening a filter
that failed to resolve is how a date-scoped lecture query returns the wrong lecture, and
it produces no error anywhere.

### 5. Index submission

Wire `index_document` from Phase 06 to the provider. Structure-preserving path mapping,
delta by content hash, removal on delete, nightly catch-up over `documents_stale_idx`.

`just reindex` and `just reindex --from-scratch`. The latter clears the resource scopes and
rebuilds from the vault and the source tables — this is I-01's enforcement and it is
exercised by a test, not just documented.

### 6. Email and calendar rendering

Render eligible `email_messages` and `calendar_events` rows as markdown into their own
resource scopes with the same `YYYY/MM/` nesting. Rebuilt by `just reindex`.

### 7. `search_vault`

Athena's tool. Typed filter parameters → dates → scopes → recall → select → read →
offload → compact hit list.

**OpenViking's MCP server is not connected to the agent** (I-09). A startup assertion
checks no `openviking_*` tool is registered.

### 8. Synthesis subagent

`CompiledSubAgent` with the enforced output schema. I-05 is structural: `answer` non-empty
with `citations` empty is rejected, retried once, then surfaced as a failure.

### 9. Evaluation harness

`tests/fixtures/retrieval_eval/` and `just eval-retrieval`, per
[`08-retrieval.md`](../08-retrieval.md#evaluation). Commit `baseline.json` at the end of
this phase.

---

## Files produced

```
src/athena/retrieval/{__init__,provider,openviking,dates,scopes,offload,schema,synthesis}.py
src/athena/agent/tools/search.py
src/athena/ml/openai_compat.py
config.example/openviking.json
prompts/synthesis.md
tests/fakes/retrieval.py
tests/fixtures/retrieval_eval/**
tests/unit/retrieval/**
tests/integration/retrieval/**
tests/acceptance/test_phase_07_retrieval_gate.py
```

## Tests required

### Scope resolution — the core of this phase

1. A single date resolves to a day-level scope.
2. A range within one month resolves to that month's scope.
3. A range spanning months resolves to the correct set of `YYYY/MM` scopes, with no gaps
   and no extras — parametrized across month and year boundaries.
4. No course → scopes across every enrolled course, and only enrolled ones.
5. **An unresolvable filter raises; it does not return an empty list.**
6. Relative date expressions resolve correctly, including across a DST boundary.
7. Vault path ↔ viking URI round-trips exactly, for every source type.

### Integration, against real OpenViking

8. **Scoped recall returns nothing from outside the scope.** This is Spike A promoted to a
   regression test and it is the most important test in the phase.
9. Every embedding call reaches `athena-ml`; assert against its request log.
10. Delta submission: reindexing an unchanged vault reports `documents_sent = 0`.
11. Deleting a vault file removes its URI; the content is no longer recallable.
12. Renaming a file removes the old URI and adds the new one.
13. `just reindex --from-scratch` reproduces equivalent results (I-01).
14. Serialized `SearchResult` for a worst-case query stays under
    `offload.max_result_tokens` (I-09).
15. No `openviking_*` tool is registered on the agent.

### **The gate**

16. `test_lecture_recall_is_correct_and_scoped` — correct answer, cited, **only** from the
    target lecture, every citation carrying a locator. See
    [`15-testing.md`](../15-testing.md#the-retrieval-gate-phase-07) for the
    `DISTINCTIVE_CLAIM` construction, which is what makes the test falsifiable rather than
    passable by a model that simply knows what RAM is.
17. `test_absent_material_is_reported_as_absent` — `insufficient`, no citations, no
    confabulation.
18. Synthesis with an empty batch returns `insufficient`.
19. A synthesis response with an answer and no citations is rejected by the schema.

### Evaluation

20. `just eval-retrieval` produces the four metrics.
21. False-answer rate on negatives is zero. **Not "low" — zero.**

## Exit gate

**All of the following, on the real machine with real course material, not only fixtures:**

1. Spikes A and B recorded, with the OpenViking version tested.
2. Ingest one real lecture recording and that week's real slide deck.
3. Ask a question answerable **only** from the transcript. Correct, quotes the instructor,
   cites that file with a timestamp.
4. Ask about material from a different week. The answer comes from that week's file.
5. Ask something the corpus does not answer. Athena says it does not know.
6. `just reindex --from-scratch`, then repeat 3–5. Same answers.
7. `just eval-retrieval` numbers recorded and `baseline.json` committed.

**If any of these fail, do not proceed to Phase 08.** Everything after this assumes
retrieval works. Building a UI and write paths on retrieval that half-works produces a
system that is confidently wrong and pleasant to use, which is the worst combination.
