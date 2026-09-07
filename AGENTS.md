# AGENTS.md

Rules for coding agents working in this repository. These are not suggestions. A change
that violates one is wrong even if it passes tests.

---

## 1. Before you write anything

**Read, in this order:**

1. `docs/README.md` — the index and the build sequence
2. `docs/02-invariants.md` — the rules no change may violate
3. **The phase document for the phase you are working on**, at
   `docs/phases/phase-NN-*.md`, in full
4. Any core document that phase's "Read first" line names

If you do not know which phase you are in, check the branch name (`phase-NN-*`), then the
most recent commits, then ask. **Do not guess.**

**Do not read the whole `docs/` tree before every task.** Read the index, the invariants,
and your phase. Pull in other documents when your phase points at them or when the change
touches their subject.

---

## 2. Phase discipline

The build is 16 phases. Each has an exit gate. **Complete only the phase you are in, then
stop at its gate.**

- Do not implement functionality belonging to a later phase because it seems convenient.
- Do not add abstraction layers for capabilities that do not exist yet.
- Do not "while I'm here" — an unrelated fix goes in its own commit at minimum, and
  usually its own PR.
- If a phase's steps appear to require something from a later phase, that is a
  specification bug. Say so and stop. Do not improvise across the gap.
- When a phase's exit gate passes, say so plainly and stop. Do not roll into the next
  phase.

The gates exist because each phase's guarantees are the next phase's assumptions.
Phase 12 (write paths) assumes Phase 03's interrupt tests passed on the pinned library
version. Skipping ahead means building a send-email path on an approval mechanism nobody
verified.

---

## 3. Non-negotiable prohibitions

Violating any of these is a serious error, not a style disagreement.

### Never commit

- `.env` or any file containing a credential
- `config/` — only `config.example/` is committed
- Vault content, `media/`, or model weights
- A dependency added without asking first (see §6)

### Never fork, patch, or vendor OpenViking

It is AGPLv3 and runs as a separate, unmodified, pinned container. Running a released
image over HTTP does not make Athena a derivative work. **Patching it makes the patch
source you must publish**, and vendoring it changes Athena's own licensing position.

If OpenViking needs to behave differently: change its configuration, change what Athena
sends it, or file an upstream issue. Never `:latest` — always an exact released tag.

### Never connect OpenViking's MCP server to the agent

The agent gets Athena's `search_vault` tool. `openviking_search` and friends return
content on their own terms and would bypass the offload and citation enforcement that
I-05 and I-09 require. A startup assertion checks this; do not remove it.

### Never weaken the approval boundary

- Never remove or narrow an entry in `config/approvals.toml`
- Never remove a tool from `interrupt_on`
- Never add an `auto_approve` rule
- Never set `ATHENA_MCP_READ_ONLY` to off in a committed file or default
- Never add a code path that executes an effect without an approval decision

If a test is failing because a tool interrupts, **the test is wrong, or your design is
wrong.** The interrupt is not the problem.

### Never violate an invariant

`docs/02-invariants.md` outranks convenience, brevity, and test-passing. If an invariant
genuinely needs to change: **change the document first, in its own commit, with the
reasoning written down.** Then change the code in a second commit. Never both in one.

### Never touch live accounts from tests

No test at any layer may authenticate to Gmail, iCloud, Google Calendar, Canvas, or
OpenRouter. The network guard in `tests/conftest.py` enforces this. **If it fires, fix the
test — do not extend the allowlist to make it pass.**

### Never run destructive commands

Forbidden without explicit instruction, in this session, for this action:

```
docker compose down -v          # destroys volumes: the vault and the database
docker volume rm / prune
docker system prune
alembic downgrade               # against a real database
git push --force                # to any branch
git reset --hard                # with uncommitted work present
rm -rf                          # anywhere outside a temp directory you created
DROP TABLE / TRUNCATE           # outside a test database
```

### Two things that look like cleanup and are not

These will look wrong to you. They are correct and they are load-bearing.

**Do not flatten the dated vault paths.** Lectures and slide decks live in
`.../lectures/YYYY/MM/`. That nesting is not a filing convention — OpenViking scopes
retrieval by path prefix, so the directory tree *is* the filter index. Flattening it
breaks date-scoped retrieval **silently**: queries still return results, just from the
wrong weeks. Same rule for the vault-path-to-`viking://` mapping, which must stay
structure-preserving. See `docs/03-decisions.md` D-02 and D-03.

**Do not return an empty scope list.** In `src/athena/retrieval/scopes.py`, a filter that
fails to resolve raises. It must never fall through to "search everything" — a silently
widened filter returns confident answers from the wrong lecture and produces no error
anywhere.

**Do not delete the queue poll as redundant.** In `src/athena/queue/`, workers both
`LISTEN` for notifications and poll on an interval. `NOTIFY` is fire-and-forget: a
notification issued while a worker is disconnected is lost forever. **The poll is the
correctness guarantee; `NOTIFY` is a latency optimization.** Removing the poll produces a
system that works in development and stalls in production. See D-07.

Both have comments saying so in the source. Do not remove those comments either.

---

## 4. Toolchain

- **Python 3.12+**, managed by `uv`. Never `pip install` directly; use `uv add`.
- **`src/` layout.** Application code in `src/athena/`, tests in `tests/`.
- **`ruff`** with `select = ["ALL"]`. Do not add to the ignore list without asking. Fixing
  the code is the default; silencing the rule is the exception and needs a reason in the
  PR.
- **`mypy --strict`** on `src` and `tests`. No `# type: ignore` without a comment naming
  the reason and, where relevant, the upstream issue.
- **`pytest`**, 100% coverage with branch coverage on. `# pragma: no cover` requires a
  justification on the same line:
  ```python
  except ImportError:  # pragma: no cover - optional MLX backend, absent in CI
  ```

Run `just check` before every commit. It runs lint, typecheck, and tests.

---

## 5. Git

**Conventional commits**, enforced by CI:

```
feat(retrieval): add reciprocal rank fusion
fix(queue): poll when the listener is disconnected
docs(invariants): clarify I-08 replay semantics
test(vault): cover symlink escape via the API layer
chore(deps): pin deepagents to 0.x.y
```

Scopes match the module: `config`, `db`, `queue`, `vault`, `ingestion`, `retrieval`,
`agent`, `approvals`, `automations`, `api`, `web`, `mcp`, `ml`, `docker`, `docs`.

**Conventional branches**, one per phase or per unit of work:

```
phase/07-retrieval
feat/retrieval-rrf
fix/queue-listener-reconnect
docs/decision-record-d19
```

**You may commit and push to a branch. You may never push to `main`.** All merges to
`main` are made by the owner through a pull request. `main` is protected; if a push to it
appears to succeed, something is misconfigured — say so.

Pull request descriptions must state: which phase, what changed, which tests were added,
and whether any invariant or decision document was touched.

**Retrieval changes have an extra requirement.** Any change to the vault path layout, the
scope resolver, OpenViking's pinned version, or its configuration MUST run
`just eval-retrieval` and report the delta against
`tests/fixtures/retrieval_eval/baseline.json` in the PR description — recall@20,
precision@8, MRR, and the false-answer rate on negatives. A retrieval change with no
numbers attached is not reviewable and will not be merged.

---

## 6. Dependencies

**Ask before adding any dependency.** Say what it does, why the standard library or an
existing dependency will not, and what its transitive footprint is.

Pin `deepagents`, `langgraph`, `langchain`, and the OpenViking image to exact versions. Upgrading them is a
deliberate act that requires re-running Phase 03's durability and interrupt tests,
because those are the guarantees that library provides and it has broken them before.

Never add a dependency to work around a bug you have not diagnosed.

---

## 7. Writing code in this codebase

**Configuration.** Nothing tunable is hardcoded (I-06). Paths, model IDs, intervals,
thresholds, prompts, lead times, timeouts — all in `config/`. Read them through
`athena.config.get_config()` at use time; **never cache a config value at import time**,
because that defeats hot reload and makes behaviour depend on start order.

**Secrets.** Only from environment variables. Config references them by variable name.
Never in a TOML file, a log, an error response, an SSE frame, the audit log, or the vault
(I-07).

**`user_id` everywhere.** Every repository function takes it as a required parameter. No
defaults, no "the current user" global (I-10).

**Time.** UTC in storage, `TIMESTAMPTZ` columns, never `datetime.now()` without `tz=`
(I-13).

**Errors.** No bare `except`. No `except: pass`. When a component needed for a decision is
unavailable, the action does not happen and the failure is surfaced (I-12). Swallowing an
error on an effect path is the worst bug class in this system.

**Determinism.** Polling, diffing, date arithmetic, and rule evaluation are plain Python.
`src/athena/automations/` may not import the agent graph or a model client (I-11). If you
find yourself reaching for an LLM to compare two dates, stop.

**Comments explain why.** The what is in the code. Where a piece of code exists because of
a non-obvious constraint — a library quirk, a protocol requirement, a performance
property — say so and reference the decision (`see D-03`).

---

## 8. Tests

Every phase's exit gate lists required tests. Write them; do not approximate them.

- **Assert observable outcomes, not mock calls.** "The email was not sent" is asserted at
  the fake transport and by the absence of an `effects` row — not by a mock's
  `assert_not_called`. A mock configured to raise would pass even if the code called it
  and swallowed the error.
- **Fakes over mocks at boundaries.** `tests/fakes/` holds shared, tested fakes for the
  email, calendar, Canvas, ML, and model boundaries. Use them.
- **Recorded fixtures are recorded by hand**, by a human, once, with secrets scrubbed and
  a `SOURCE.md` recording provenance. No test may record a fixture.
- **Concurrency tests need committed data.** The default rollback-per-test fixture makes
  `SKIP LOCKED` tests silently vacuous. Use the per-schema fixture.
- **Do not delete or skip a failing acceptance test to make a phase pass.** If an
  acceptance test fails, the phase is not done. Say so.

---

## 9. When something is wrong

- **The specification is unclear or contradictory** → say so, quote the passage, propose
  the resolution, and wait. Do not pick one and proceed silently.
- **A phase requires something from a later phase** → stop and report it. That is a
  planning bug, and improvising across it produces the coupling the phasing exists to
  prevent.
- **A library does not behave as the docs claim** → verify against the installed version,
  write a failing test that demonstrates it, and report it before working around it.
  `docs/03-decisions.md` D-01 lists known `deepagents` sharp edges; add to that list.
- **You are about to violate an invariant** → stop. Explain what you were trying to do and
  which invariant blocks it. The invariant is probably right; if it is not, it changes in
  its own commit first.
- **A test fails and you do not understand why** → do not delete it, do not add a pragma,
  do not weaken the assertion. Report it.

---

## 10. What "done" means

A task is done when:

- The phase document's steps are complete
- Every test the phase requires exists and passes
- `just check` is green
- Coverage is 100% with no unjustified pragmas
- No invariant is violated
- The changes are committed with conventional messages on a conventional branch and
  pushed
- The PR description states the phase, the change, the tests, and — for retrieval changes
  — the evaluation deltas

Then stop and say the gate is met. **Do not start the next phase.**
