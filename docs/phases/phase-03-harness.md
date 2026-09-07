# Phase 03 — Deep Agents harness and durability

**Objective.** A minimal agent that runs, checkpoints to Postgres, survives being killed
mid-run, and resumes on the same `thread_id`. Plus the interrupt mechanism proven end to
end — approve, edit, **and** reject — including from inside a subagent.

**Preconditions.** Phase 02 gate green.

**Why before anything useful.** The handoff's original sequencing is right: prove
durability with a toy tool before wiring anything real. Every later guarantee (I-08, the
approval boundary) rests on checkpoint/resume actually working with the pinned library
version.

---

## Steps

### 1. Dependencies

```bash
uv add deepagents langgraph langchain langgraph-checkpoint-postgres langchain-openai
```

Pin `deepagents` to an exact version. Record the version in
[`03-decisions.md`](../03-decisions.md#d-01--harness-deepagents) and re-run this phase's
tests on every upgrade.

`langchain-openai` is the OpenRouter client — OpenRouter is OpenAI-API-compatible, so
point `base_url` at it (D-10). Do not add a provider-specific SDK.

### 2. Model routing

`src/athena/agent/models.py`, implementing `model_for_role` from
[`09-agent.md`](../09-agent.md#model-routing).

Everything here matters on a free tier:

- A shared async token-bucket limiter keyed by role.
- Exponential backoff with jitter on 429, bounded by `rate_limits.max_retries`.
- `RateLimitExhausted` raised when the budget is spent; **the worker returns the job to
  the queue with a future `run_after` rather than failing the run.** A rate limit is a
  scheduling problem, not an error.
- Fallback walk on unavailability, logging which model served the call.

### 3. Checkpointer

`AsyncPostgresSaver` against the same database. Run its `setup()` in the migration path,
not lazily at runtime, so the tables exist before the first run and their creation is not
a race between workers.

### 4. Minimal graph

`build_agent` from [`09-agent.md`](../09-agent.md#graph-construction), with:

- `StateBackend` only (the vault arrives in Phase 04)
- two toy tools: `echo` (read-like) and `record_effect` (write-like, declared as an effect
  tool, writes a row to a scratch table so an external effect is observable)
- `interrupt_on` for `record_effect`
- one trivial subagent that also has `record_effect`, to exercise subagent inheritance

### 5. The effect executor

`src/athena/agent/effects.py`, implementing I-08:

```python
async def execute_effect(session, *, run_id, tool_call_id, kind, request, fn):
    """Persist-before-execute with replay safety.

    1. INSERT effects row as 'pending'. On conflict, the effect already exists:
       read it and return its recorded outcome without calling fn. COMMIT.
    2. Call fn.
    3. UPDATE to 'succeeded'/'failed' with the response. COMMIT.

    Step 1 commits before step 2 on purpose. If the process dies between them, a
    'pending' row survives and the reconciler surfaces it to the owner rather
    than guessing -- because "did the email send" cannot be safely inferred, and
    guessing wrong in either direction is bad.
    """
```

The effect registry — the declaration that makes a tool an effect tool — also lives here,
along with the completeness test that catches a write tool added without a declaration.

### 6. Run orchestration

`src/athena/agent/runner.py`: the `agent.run` job handler.

- Creates or resumes a `runs` row.
- Streams graph events into `run_events` with monotonic `seq`.
- On `interrupt`: writes the `approvals` row, sets `runs.status = 'waiting_approval'`,
  **completes the job** (releasing the worker), and returns. A paused run must occupy
  nothing.
- On resume: a separate `agent.resume` job kind invokes with `Command(resume=decision)`.

### 7. Approval store

`src/athena/approvals/` — create, decide, expire. The UI is Phase 10; this phase drives
it through a repository API so durability can be tested now.

---

## Files produced

```
src/athena/agent/{__init__,graph,models,backend,interrupts,effects,runner,subagents}.py
src/athena/agent/tools/{__init__,toy}.py
src/athena/approvals/{__init__,store,expiry}.py
prompts/orchestrator.md
tests/integration/agent/**
tests/acceptance/test_phase_03_durability.py
```

## Tests required

### Durability

1. Run a multi-step task; kill the worker process mid-run; restart; resume the same
   `thread_id`; assert it continues from the checkpoint rather than restarting.
2. Assert `record_effect` executed exactly once across that boundary.
3. Restart the whole stack (including Postgres) with a run interrupted; assert it is still
   resumable.

### Interrupts — all three decisions

4. `approve` → the tool executes with the original arguments.
5. `reject` → the tool never executes; **assert at the scratch table**, not at a mock.
6. `edit` → the tool executes with the edited arguments; assert the edited values landed.
7. **All three, from inside the subagent.** `deepagents` has had bugs where subagent
   resume works for `approve` but not `edit`/`reject`
   ([`03-decisions.md`](../03-decisions.md#d-01--harness-deepagents)). If they fail on the
   pinned version, that is a phase blocker: pin forward, patch, or restructure so effect
   tools are only on the orchestrator. **Do not proceed to Phase 12 with this unverified.**

### Startup assertions

8. A tool declared as an effect with no rule in `approvals.toml` prevents startup, with an
   error naming the tool.
9. The per-subagent resolved rule set is asserted, and a subagent declaring `permissions`
   that would drop inherited rules is caught.

### Rate limiting

10. A 429 triggers backoff and eventual success.
11. Exhausted budget raises `RateLimitExhausted`, and the worker requeues the job with a
    future `run_after` rather than marking the run failed.
12. Primary model unavailable → fallback used, and the serving model is recorded on the
    run event.

## Exit gate

- All of the above pass.
- The kill-and-resume test passes ten consecutive runs (it is a race; one pass is not
  evidence).
- Subagent `edit` and `reject` verified on the pinned version, or a documented mitigation
  is in place and referenced from `03-decisions.md`.
