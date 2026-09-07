# 03 — Decision record

Each entry: the decision, why, what it costs, and the condition under which it should be
revisited. A decision with no reversal condition is dogma.

Rejected alternatives from the pre-project evaluation (Hermes, Khoj, OpenClaw, LangSmith
Fleet, LangGraph Agent Server) are settled and are not restated here. The short version:
each meant adopting someone else's orchestration model rather than owning it, and each
had a concrete disqualifier. Do not re-propose them without new information.

---

## D-01 — Harness: `deepagents`

**Decision.** Build on LangChain's `deepagents` package: `create_deep_agent`, its
middleware stack, `CompositeBackend`, `interrupt_on`, `permissions`, subagents.

**Why.** It supplies exactly the four primitives this project needs — planning tool,
subagents, a pluggable filesystem, HITL interrupts — without supplying an opinionated
memory model, a config format, or a serving layer. The orchestration above those
primitives stays ours, which was the point.

**Cost.** A dependency on a fast-moving library. Pin it exactly; upgrades are deliberate.

**Known sharp edges to verify on the installed version:**
- Subagent interrupt resume has had bugs where `approve` works but `edit`/`reject` do
  not (`langchain-ai/deepagents#554`). Phase 03 MUST test all three decision paths
  through a subagent, not just approve. `TODO(verify)` against the pinned version.
- `permissions` is applied by `FilesystemMiddleware` at the tool level and **does not
  apply to direct backend use**. This is why I-04 requires the backend root as a second
  wall rather than trusting `permissions` alone.
- Subagents inherit parent `interrupt_on` unless they declare their own `permissions`,
  which replaces the parent's rules entirely. A subagent that declares `permissions`
  therefore silently drops inherited approval rules. Phase 12 MUST assert the resolved
  rule set per subagent at startup.

**Revisit if.** The library's release cadence breaks us more than twice in a semester, or
a needed primitive is removed.

---

## D-02 — Retrieval: OpenViking

**Decision.** Retrieval is provided by **OpenViking**, running as a container in the
stack. Athena owns the vault, ingestion, the agent-facing tool contract, and synthesis.
OpenViking owns chunking, embedding, tiering, indexing, and search.

**Why.** Three reasons, in order of weight.

1. **It is a large amount of code Athena does not have to own.** Chunking strategies per
   source type, delta indexing, hybrid search, rank fusion, reranking, and the
   maintenance around all of it was the single biggest deliverable in the build. Removing
   it removes the largest source of subtle, hard-to-test bugs.
2. **Path-scoped retrieval is the right shape for this corpus, and it is their core
   design.** OpenViking indexes `viking://` paths as a first-class scope boundary applied
   *before* vector search and reranking — not as scalar metadata filtered afterward. The
   flagship query ("what did my instructor say about RAM on September 8th") is primarily a
   scope with similarity as the tiebreak inside it. Coursework is already a tree. This
   matches better than a hand-built filter would.
3. **Recall returns pointers, not payloads.** OpenViking's recall gives candidate URIs
   plus abstracts, and you read the ones you want. That is natively the offload pattern
   I-09 requires, rather than something Athena has to impose on a search API that wants to
   return text.

**Cost, and it is real:**

- **A second stateful service.** Another thing to back up, restart, and diagnose. Mitigated
  by I-01: its store is derived, so recovery is "reindex," not "restore a vector
  database."
- **AGPLv3.** Running it unmodified as a separate process over HTTP does not make Athena a
  derivative work. But **any patch to OpenViking becomes source you must publish**, and
  offering Athena as a hosted service obliges offering OpenViking's source to its users.
  The practical rule, encoded in `AGENTS.md`: never vendor, fork, or patch it. Pin a
  released version and configure it.
- **Retrieval quality is now partly someone else's roadmap.** Mitigated by keeping
  Athena's own evaluation set (see [`08-retrieval.md`](08-retrieval.md#evaluation)) and
  treating an OpenViking upgrade as a retrieval change requiring evaluation deltas.
- **Memory footprint on a 16 GB machine.** It replaces `athena-ml`'s reranking role but
  adds a server and its own store. Budgeted in
  [`14-deployment.md`](14-deployment.md#resource-budget-on-16-gb).

**Two things it forces on the rest of the design:**

- **Date must be encoded hierarchically in the vault path** (`lectures/2026/09/...`), so a
  date range is expressible as a set of path scopes. See
  [`05-vault-schema.md`](05-vault-schema.md).
- **Agent evolution and auto-capture are disabled.** Extracted memories are the model's
  restatement, which is the thing I-02 exists to prevent, and a second opaque memory
  channel makes "why does it think that" unanswerable.

**Revisit if.** Evaluation on Athena's own query set falls below the acceptance bar and
configuration does not recover it; or the project's licensing or hosting terms change in a
way that affects a public repo. The fallback is D-19.

---

## D-03 — Scope resolution is Athena's, not OpenViking's

**Decision.** Athena computes `viking://` path scopes in Python from the resolved filters
and passes them explicitly to recall. It does not rely on OpenViking exposing scalar
date-range filters.

**Why.** Whether the open-source edition exposes arbitrary scalar filters is unclear from
its documentation and is a moving target across versions. Path scoping is documented,
stable, and central to the product. Computing the scope set from the calendar and the
enrolled-course list is deterministic work Athena is already doing (I-11), so it costs
almost nothing and removes a dependency on a feature that might change.

It also keeps the filter semantics testable in Athena's own test suite rather than only
observable through a third-party search result.

**Cost.** A month-granularity floor: a range narrower than a month is scoped to the month
and ranked within it. At this corpus size that has no measurable precision effect.

**Revisit if.** OpenViking's scalar filter support is confirmed stable and covers time
ranges, and the month floor ever becomes a measured problem.

---

## D-04 — Postgres remains, without pgvector

**Decision.** Postgres continues to hold state, source mirrors, and the job queue. It no
longer holds chunks, embeddings, or a vector index, and the `vector` extension is not
installed.

**Why.** The reasons for Postgres as the state store and job queue (D-07) were never about
retrieval. Removing the index tables removes the largest and most write-heavy part of the
schema and the whole class of embedding-dimension migration problems.

`documents` survives in reduced form as a vault-file registry — it is what ingestion
tracking, conflict records, and the Canvas file mapping point at, and what tells the
indexer which files have changed. It carries no vectors.

---

## D-05 — Embeddings stay local

**Decision.** OpenViking is pointed at an OpenAI-compatible embedding endpoint served by
Athena's own `athena-ml` container. Embeddings never leave the machine.

**Why.** Every ingested document is embedded. Coursework and full inbox contents would
otherwise be transmitted in their entirety. OpenViking supports `local`, `ollama`, and
`litellm` providers with a custom `api_base`, so this costs one configuration block.

**Note the asymmetry, because it is easy to misread as full privacy.** Embeddings are
local. OpenViking's semantic processing (L0/L1/L2 tiering) calls a VLM, and Athena's
synthesis calls OpenRouter. **Any document that is retrieved for a query is transmitted.**
The corpus as a whole is not; individual retrieved documents are. Recorded as an accepted
risk in [`13-security.md`](13-security.md#known-accepted-risks).

**Revisit if.** A local model becomes viable for the synthesis role.

---

## D-06 — ML services are HTTP endpoints with two implementations

**Decision.** `athena-ml` (embeddings, OpenAI-compatible) and `athena-asr` (transcription)
are HTTP services behind versioned contracts, each with a container implementation (CPU,
portable, used in CI) and a host implementation (native macOS, MLX/Metal, used in
production). Config selects the base URL.

**Why.** Forced, then chosen. Docker on macOS runs containers inside a Linux VM under
`Hypervisor.framework`, which exposes no virtual GPU — a container on this Mac mini cannot
reach Metal or the Neural Engine. Whisper large-v3 on VM CPU is roughly an order of
magnitude slower than on Metal, which is the difference between a lecture being searchable
in three minutes and in forty. Since the ASR worker must be a host process, it must be
reached over a socket; and once that is true, giving embeddings the same shape costs
nothing and lets OpenViking consume them over the same interface.

**Cost.** One component of "fully containerized" is not, on macOS, and there are two code
paths. Both are exercised — container in CI, native by a smoke test on the host.

**Revisit if.** Apple exposes GPU virtualization to `Hypervisor.framework`.

---

## D-07 — Postgres is the job queue

**Decision.** `jobs` table, `SELECT ... FOR UPDATE SKIP LOCKED`, `LISTEN`/`NOTIFY` for
wakeup. No Redis, no Celery, no RabbitMQ.

**Why.** Transactional enqueue (an approval and its notification commit together), one
fewer stateful service to back up and restore, and throughput requirements three orders
of magnitude below what `SKIP LOCKED` handles.

**Critical property.** `NOTIFY` is fire-and-forget — a notification issued while a worker
is disconnected is lost. Workers MUST also poll on an interval. `NOTIFY` is a latency
optimization; the poll is the correctness guarantee. A worker that only listens will
appear to work in development and stall in production.

**Revisit if.** Job volume exceeds a few thousand per minute, or fan-out to many workers
is needed.

---

## D-08 — One MCP server per integration, in its own container

**Decision.** Athena ships its own MCP servers for email, calendar, and Canvas, one
container each, over streamable HTTP.

**Why.** Two parts.

*Why our own:* the original plan was to reuse existing MCP servers. That holds for
Canvas, where mature servers exist. It does not hold across email and calendar: the
account set is Gmail (OAuth), iCloud (IMAP/SMTP + app-specific password), Google Calendar
(OAuth), and Apple Calendar (CalDAV + app-specific password). OSU Outlook is out —
Microsoft Graph requires an Entra app registration in OSU's tenant, which the owner
cannot obtain. Assembling three or four third-party servers with inconsistent tool
surfaces, inconsistent error semantics, and inconsistent auth handling is more integration
work than one server with provider adapters, and it makes the approval boundary harder to
reason about because every server names its write tools differently.

*Why separate containers:* credential isolation. The email server holds mail credentials
and nothing else does. A prompt-injected tool argument or a parsing bug in the Canvas
server cannot reach the mail password, because it is not in that process's environment.

**Cost.** We maintain the adapters. Mitigated by keeping each adapter thin — the MCP
servers do protocol translation and nothing else, with no business logic.

**Revisit if.** A maintained MCP server appears that covers Gmail + IMAP + CalDAV +
Google Calendar with a coherent tool surface.

---

## D-09 — OSU Outlook is out of scope; iCloud via IMAP

**Decision.** MVP email accounts are Gmail (API + OAuth) and iCloud (IMAP/SMTP +
app-specific password), plus a generic IMAP/SMTP adapter for anything else. OSU mail is
not integrated.

**Why.** The owner cannot register an application in OSU's Entra tenant, which Microsoft
Graph requires, and university tenants have generally disabled IMAP basic auth. There is
no path that does not depend on an approval the owner cannot get.

**Cost.** Coursework email arriving at the OSU address is invisible to Athena.

**Workaround to document, not to build:** forwarding OSU mail to an ingested account
brings the content in. Note that replies then originate from the forwarding address,
which may be wrong for academic correspondence — this is the owner's call, not Athena's.

**Revisit if.** OSU permits app registration, or ships a delegated-permission path.

---

## D-10 — OpenRouter free-tier models, per-role routing

**Decision.** All LLM calls go through OpenRouter. Every role — triage, synthesis,
drafting, vision (PDF conversion), vault-writing — has its own model ID in
`config/agent.toml`.

**Why.** One credential, one client, and swapping a model is a config edit. Per-role
routing from day one because the roles have genuinely different requirements — vision
conversion needs an image-capable model, triage needs to be cheap and fast, synthesis
needs reasoning quality — and because it is the knob you will actually reach for when
tuning cost later.

**Consequences of the free tier that the design MUST absorb:**
- **Rate limits are aggressive.** Every model call goes through a shared limiter with
  exponential backoff and jitter; a rate-limited job returns to the queue rather than
  failing the run. Configure per-role concurrency caps.
- **Tool-calling reliability varies.** Free models are more likely to emit malformed tool
  calls. The agent loop needs a bounded retry with a repair prompt, and the deterministic
  half of the system (I-11) becomes more valuable, not less.
- **Availability is not guaranteed.** Each role config takes a `fallbacks` list of model
  IDs tried in order.

**Revisit if.** The free tier's quality or rate limits block the acceptance gate. Ollama
remains deferred; the host-service pattern from D-06 is the path if it returns.

---

## D-11 — Audio is transcribed on the Mac mini, not on the capture device

**Decision.** The iPhone and MacBook record audio and upload the file through the Athena
web UI. Transcription happens on the Mac mini via `athena-asr`.

**Why.** One transcription implementation, one model version, one place to fix quality
problems. Capture devices vary; the transcript format must not.

**Choice of stack.** WhisperX-shaped: faster-whisper for decode, wav2vec2 forced
alignment for word-level timestamps, pyannote for diarization. On Apple Silicon the
decode backend is MLX so it uses the GPU. Timestamps are not optional — they are what
makes a 90-minute lecture navigable, and what lets a citation point at a moment rather
than at a file. Diarization is configurable and on by default for lectures, so that
instructor speech can be separated from classroom questions.

**Cost.** Several models resident on the host; a `launchd`-managed process outside Docker.

**Revisit if.** On-device transcription quality on iOS reaches parity and the format can
be pinned.

---

## D-12 — PDFs are converted page-image → markdown by a vision model

**Decision.** Slide decks and other PDFs are rasterized one image per page and converted
to markdown by a vision model, rather than text-layer extraction.

**Why.** CS slide decks carry most of their content in diagrams, code screenshots, and
layout. Text extraction returns a bag of fragments with the structure removed, and
returns nothing at all for image-only slides. A vision model produces markdown that
preserves headings, code blocks, table structure, and a description of each figure.

**Cost.** One model call per page. On free-tier models this is slow and rate-limited, so
conversion is a background job with per-page checkpointing — a failure at page 40 of 60
resumes at page 40.

**Note on I-02.** Per-page markdown *is* a lossy conversion, so the original PDF is
retained under `media/` and referenced from frontmatter. A citation can always be
resolved back to the page image.

**Revisit if.** Per-page cost or latency becomes the bottleneck; a text-layer fast path
for text-only PDFs is the obvious optimization, gated on a detector.

---

## D-13 — Approvals are a review queue with per-action auto-approval and expiry

**Decision.** Interrupts create rows in `approvals`. The owner clears them from the UI.
Each has a configurable expiry after which it is auto-rejected. Auto-approval exists only
per action, only when explicitly configured.

**Why.** An always-on daemon generates approvals while the owner is in class. A modal
prompt is the wrong shape; a queue with push notification is the right one. Expiry is
required because an interrupt holds a paused run, and "send this email" is rarely still
correct three days later.

**Design constraint.** Expiry resolves to **reject**, and the run is resumed with that
decision so the agent observes the outcome and can react. It MUST NOT be a silent
timeout that leaves the run wedged.

**Revisit if.** Approval volume makes the queue a chore — at which point the answer is
better pre-filtering (fewer proposed actions), not looser approval.

---

## D-14 — Web Push, delivered to a home-screen PWA

**Decision.** Notifications are Web Push (VAPID) to the browser and to the iOS PWA.

**Why.** One implementation covers desktop and mobile, requires no app store, and
integrates with the existing UI session.

**Hard constraint.** On iOS, the Push API is available **only** to a web app installed to
the Home Screen — an open Safari tab cannot receive push, and this is Apple's design, not
a configuration problem. It requires a manifest, a secure context, and a user gesture
before the permission prompt. Tailscale's HTTPS certificates for `*.ts.net` satisfy the
secure-context requirement with a publicly trusted certificate. The setup doc MUST
instruct the owner to install the PWA before expecting notifications.

**Cost.** A service worker, VAPID key management, and per-device subscription records.

**Fallback if push proves unreliable:** an in-UI badge is always authoritative; push is a
delivery optimization. Never make an approval reachable only through a notification.

---

## D-15 — Configuration is TOML files validated by Pydantic Settings, hot-reloaded

**Decision.** `config/` holds one TOML file per domain, loaded into Pydantic Settings
models with `extra="forbid"`, watched for changes and swapped atomically at runtime.

**Why.** TOML parses from the standard library, supports comments, and has a type system
that maps cleanly onto Pydantic. One file per domain keeps each readable. `extra="forbid"`
turns a typo into a startup error instead of a silently ignored setting — which is the
single most common way a heavily-configurable system lies to its operator.

**Hot reload is not free** and the design must respect it: reload swaps an immutable
config object behind a getter. Components MUST call the getter, never cache a value at
import time. Some settings cannot be hot-applied (bind address, database URL); those are
marked `reload=False` in their model and a change to one logs a warning that a restart is
required, rather than pretending it took effect.

**Revisit if.** The config surface grows past what a human can hold — at which point the
answer is better defaults and fewer knobs, not a different format.

---

## D-16 — SPA plus FastAPI, not server-rendered

**Decision.** React + TypeScript + Vite SPA, served as static files by the API container,
talking to FastAPI over JSON and SSE.

**Why.** The surface — streaming chat, live approval queue, ingestion progress, trace
viewer — is genuinely stateful and genuinely real-time. HTMX would be less code for the
CRUD parts and worse for every part that streams. The PWA requirement (manifest, service
worker, offline shell) also lands naturally in a JS build.

**Cost.** A second toolchain and a second test stack.

**Revisit if.** Never, realistically. Recorded so the choice is not re-argued.

---

## D-17 — Session auth with a user table from day one

**Decision.** Login with username and password (Argon2id), server-side sessions in
Postgres, `HttpOnly` `Secure` `SameSite=Strict` cookies. A `users` table exists and
everything references it.

**Why.** Tailscale is the network boundary, but it is not an authorization boundary: any
device on the tailnet, including a compromised one, reaches the service. More
importantly, I-10 requires `user_id` on every row, and adding an owner column later is a
migration across every table.

**Cost.** A login screen for a single-user system.

**Revisit if.** Never. This is cheap insurance.

---

## D-18 — Coverage at 100%, branch included

**Decision.** `--cov-fail-under=100`, `branch = true`. `# pragma: no cover` is permitted
only with a justification comment on the same line.

**Why.** Owner's requirement. Worth stating the real trade-off honestly: reaching 100%
on MCP, network, and Docker glue requires substantial mocking, and mock-heavy tests
verify that the code calls what you told it to call, not that it works. The mitigation is
the layering in [`15-testing.md`](15-testing.md) — unit tests for logic, integration
tests against real Postgres and a real ML service in a container, recorded-fixture tests
for external APIs, and acceptance tests that assert observable outcomes. Coverage is a
floor, not the goal.

**Revisit if.** Coverage work starts displacing acceptance-test work. The signal is
pragma density climbing.

---

## D-19 — Superseded: the hand-built pgvector design

**Status.** Superseded by D-02. Recorded because it is the documented fallback, and
because knowing what was rejected and why makes the reversal condition actionable.

**What it was.** Chunks, embeddings, and denormalised filter columns in Postgres with
`pgvector`; per-source-type chunking; delta indexing by content hash; hybrid dense +
Postgres full-text search fused by Reciprocal Rank Fusion; a local cross-encoder reranker;
exact search with no ANN index at MVP scale.

**Why it was displaced.** Not because it was wrong — it would have worked, and its filter
semantics were sound. It was displaced because OpenViking does the same job, its
path-scoped index is a better structural match for a corpus that is already a tree, and
the code it removes was the largest and most bug-prone deliverable in the build. The
original argument that building it was the learning objective was set aside by the owner
as not a priority, which removed its main remaining support.

**If reverting to it**, the details that were load-bearing and are easy to get wrong:

1. **No ANN index at MVP scale.** With HNSW, filters are applied after the index scan: at
   the default `hnsw.ef_search = 40`, a filter matching 10% of rows yields roughly four
   results, and a selective filter can return zero. Exact search over tens of thousands of
   rows is single-digit milliseconds with 100% recall.
2. **Same query level.** If HNSW is enabled, the `WHERE` clause and the
   `ORDER BY embedding <=> :q` must sit at the same query level. A CTE boundary between
   them silently disables pgvector's iterative scan.
3. **Denormalised filter columns on `chunks`** — deliberately unnormalised, so the filter
   and the vector ordering are not separated by a join.
4. **The chunk hash must cover the final embedded text**, heading path included, or a
   section rename does not invalidate the vector.
5. **RRF fuses by rank, not score.** Cosine similarity and `ts_rank_cd` are not on
   comparable scales and normalising them means maintaining calibration constants that go
   stale.

**Revert if.** D-02's revisit condition fires.
