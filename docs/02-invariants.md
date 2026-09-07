# 02 — Invariants

These are the rules that outrank convenience. A change that violates one is wrong even
if it passes tests, even if it is smaller, even if the alternative is annoying. If an
invariant genuinely needs to change, it changes here first, in a commit of its own, with
the reasoning written down — and then the code follows.

Each invariant states the rule, the mechanism that enforces it, and the failure it
prevents. An invariant with no enforcement mechanism is a wish, not an invariant.

---

## I-01 — The vault is the only source of truth

Every fact Athena can recall traces back to a file in the vault or a row in a source table
(`email_messages`, `calendar_events`, `canvas_assignments`). **OpenViking's store is
derived and disposable.** Dropping it entirely and reindexing MUST lose nothing.

**Enforced by:** `just reindex --from-scratch` clears OpenViking's resource scopes and
re-adds everything from the vault and the source tables. An acceptance test runs it and
asserts search results are equivalent afterward.

**Prevents:** the retrieval layer becoming the only copy of something. This is also what
makes D-02 reversible: swapping retrieval providers is a reindex, not a migration. The
invariant earns its cost precisely here.

---

## I-02 — Source text is never paraphrased away

Ingestion may add derived artifacts — a summary, extracted metadata, a per-page markdown
rendering — but MUST NOT replace the original wording with a model's restatement of it.
Where a conversion is lossy by nature (audio → text, PDF page → markdown), the original
artifact is retained under `media/` and referenced from the document's frontmatter.

**Enforced by:** every converter writes `source_media` into frontmatter; a test asserts
that for every document with a `source_media` reference, the referenced file exists.

**Prevents:** the exact failure mode that ruled out fact-extraction memory frameworks.
"What did my instructor say about RAM" is a question about wording. A pipeline that
stores the model's summary of the lecture cannot answer it, and worse, will produce a
fluent answer that sounds right.

---

## I-03 — Every effect passes the approval boundary

An **effect** is any action with a consequence outside Athena: sending email, creating or
modifying a calendar event, writing to Canvas, or any future write tool. Every effect
MUST be produced by a tool listed in `config/approvals.toml`, and MUST pass through
`interrupt_on` before executing.

Enforcement is at the tool boundary. It is **never** the system prompt's job. The model
is not asked to police itself, is not trusted to, and a prompt regression must not be
able to open a write path.

**Enforced by:**
- A startup assertion: every tool whose name matches the effect registry MUST have an
  entry in the resolved `interrupt_on` map, or the process refuses to start.
- An acceptance test per effect tool: reject the interrupt, then assert the external
  system was never called (fixture-level assertion, not a mock's return value).

**Prevents:** an agent that emails your professor at 3am because a retrieved document
contained instructions.

---

## I-04 — Filesystem access is fenced

The agent's filesystem tools reach the vault root and the ephemeral state backend, and
nothing else. Paths are resolved and checked against the configured root **after**
symlink resolution, before any I/O.

**Enforced by:** `CompositeBackend` routes `/vault/` to a `FilesystemBackend` rooted at
`ATHENA_VAULT_ROOT`, plus `permissions` rules on the filesystem tools. Both, not either:
`permissions` is applied by `FilesystemMiddleware` at the tool level and does not apply to
direct backend use, so the backend root is the second wall.

**Prevents:** `../../../etc/passwd`, and its more realistic cousin, an agent helpfully
reading `.env` because it was looking for configuration.

---

## I-05 — Ground or abstain

A synthesized answer either cites the vault paths and source rows it drew on, or states
that it found nothing. It MUST NOT answer a question about the owner's material from the
model's own knowledge.

**Enforced by:** the synthesis subagent's output schema requires a non-empty `citations`
array whenever `answer` is non-empty; a response with an answer and no citations is
rejected and retried once, then surfaced as a failure.

**Prevents:** the acceptance test passing vacuously. A model that knows what RAM is will
produce a plausible answer to the lecture question while retrieving nothing at all.

---

## I-06 — Nothing tunable is hardcoded

If a reasonable operator might want to change it, it lives in `config/`. This includes
paths, model IDs, intervals, lead times, chunk sizes, thresholds, prompts, sender rules,
quiet hours, retention windows, and every timeout.

Literals permitted in code: protocol constants, mathematical constants, and defaults
declared **inside a Pydantic config model** (which is the config surface, not a
bypass of it).

**Enforced by:** a lint test that greps `src/athena/` for a denylist of literal patterns
(absolute paths, bare `time.sleep(<number>)` outside tests, model-name string literals)
and fails on a hit not annotated with a justification.

**Prevents:** the retrofit tax. Every hardcoded value is a future edit in N places.

---

## I-07 — Secrets live in exactly one place

Secrets are supplied as environment variables, sourced from `.env` or Docker secrets.
They MUST NOT appear in: `config/*.toml`, the vault, the index, logs, SSE frames, the
audit log, agent context, or the repository.

Config refers to secrets **by variable name**, never by value:

```toml
[accounts.email.personal]
provider = "imap"
password_env = "ATHENA_ICLOUD_APP_PASSWORD"   # correct
# password = "hunter2"                         # never
```

**Enforced by:**
- Pydantic validators reject any config key ending in `_env` whose value looks like a
  secret rather than a variable name, and reject config keys named `password`,
  `token`, `secret`, or `api_key` outright.
- A logging filter redacts values of every known secret env var from every log record.
- `gitleaks` runs in CI and as a pre-commit hook.

**Prevents:** a public repo with credentials in it.

---

## I-08 — Persist before you execute

Before an effect executes, the intent to execute it MUST be committed to Postgres. After
it executes, the outcome MUST be committed. Every effect carries an idempotency key, and
replaying a run MUST NOT repeat an effect already recorded as done.

**Enforced by:** the `effects` table with a unique constraint on
`(run_id, tool_call_id)`; the effect executor checks for a completed row before calling
out, and writes the pending row in the same transaction that releases the approval.

**Prevents:** the container restarting between "approved" and "sent" and either losing the
send or doing it twice. This is borrowed directly from Hermes's durability guarantee and
is the single most valuable idea in that report.

---

## I-09 — Retrieved content never enters the main thread

The retrieval tool returns a compact hit list — vault path, viking URI, locator, score,
short preview — and writes full content to `/retrieved/{batch_id}/`. Synthesis is
delegated to a subagent scoped to that batch.

OpenViking's recall returns pointers rather than payloads, so this is the natural shape
rather than something imposed on it. But the enforcement stays Athena's: the agent is
given Athena's `search_vault` tool, **never OpenViking's MCP tools directly**, because
those return content on their own terms and would put it in the main thread.

**Enforced by:** the search tool's return type is a fixed-schema list with a per-preview
character cap; a test asserts the serialized tool result stays under the configured token
budget for a worst-case query; a test asserts no OpenViking MCP tool is registered on the
agent.

**Prevents:** context exhaustion, and the cost curve where every question costs more than
the last because the thread accumulates lecture transcripts.

---

## I-10 — Single user today, no single-user assumptions

Every row that belongs to a person carries `user_id`. Every query filters on it. No code
path resolves "the user" from a global, a config singleton, or the assumption that there
is exactly one row in `users`.

**Enforced by:** repository functions take `user_id` as a required parameter — no
defaults. A test asserts that a second user's data is invisible to the first through
every read path.

**Prevents:** the rewrite. This costs almost nothing now and is very expensive later.

---

## I-11 — Deterministic work stays deterministic

Polling, diffing, date arithmetic, lead-time calculation, and rule evaluation are plain
Python. The LLM is invoked only where the correct output is genuinely contestable.

**Enforced by:** `src/athena/automations/` MUST NOT import the agent graph or a model
client. It enqueues a run when it needs judgment. A test asserts the import graph.

**Prevents:** nondeterministic reminders, unnecessary cost, and a model regression
breaking your due-date tracking.

---

## I-12 — Degrade closed

When a component required for a decision is unavailable, the action does not happen and
the failure is surfaced. Athena MUST NOT proceed with a partial picture on an effect
path.

Concretely: if the approval store is unreachable, no effect executes. If retrieval fails,
the answer is "retrieval failed," not an ungrounded answer. If the ASR service is down,
the audio stays queued; it is not transcribed by a fallback of lower quality without the
owner being told.

**Enforced by:** effect execution requires a successful read of an `approved` row inside
the executing transaction; there is no `except: pass` on that path. Lint forbids bare
`except` in `src/athena/`.

---

## I-13 — Time is UTC in storage, local at the edges

Every timestamp is stored as `TIMESTAMPTZ` in UTC. Conversion to the owner's timezone
happens in the API response layer and the UI. Cron and lead-time expressions are
evaluated in the configured timezone, then converted.

**Enforced by:** a test that asserts every `TIMESTAMP` column in the schema is
`WITH TIME ZONE`; a lint rule forbidding `datetime.now()` without `tz=`.

**Prevents:** the semester where every reminder is an hour early because DST changed.

---

## I-14 — Tests never touch a live account

No test, at any layer, may authenticate to Gmail, iCloud, Google Calendar, Canvas,
OpenRouter, or any other external service. External behaviour is reproduced from
recorded fixtures.

**Enforced by:** a `conftest.py` autouse fixture that patches the socket layer to raise
on any connection to a host outside the allowlist (`localhost`, the test Postgres,
the test ML service). A test that needs the network must fail loudly, not silently
reach the internet.

**Prevents:** a test run emailing someone.

---

## I-15 — The approval boundary cannot be widened by the agent

The agent has no tool that edits `config/approvals.toml`, adds an auto-approve rule,
or modifies `interrupt_on`. Auto-approval is configured by the owner, in a file, out of
band.

**Enforced by:** the vault filesystem fence (I-04) excludes `config/`; there is no
config-write tool; a test asserts no registered tool can reach the config directory.

**Prevents:** the obvious attack, and the less obvious one where the agent reasons its
way into "the user clearly wants me to stop asking."
