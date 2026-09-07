# 06 — Data model

One Postgres 17 instance holds four concerns: **state** (users, threads, approvals,
effects), **a vault registry** (documents), **source mirrors** (email, calendar, Canvas),
and **the job queue**. LangGraph's checkpointer manages its own tables and is not
described here.

**There is no vector index here.** Retrieval is OpenViking's (D-02); the `vector`
extension is not installed and there are no chunk or embedding tables. If you are looking
for them because a phase document mentions chunking, you are reading a stale reference —
report it.

Conventions:

- All primary keys are ULIDs stored as `TEXT`, except where an external system's ID is
  the natural key. ULIDs sort by creation time, which makes cursor pagination trivial.
- All timestamps are `TIMESTAMPTZ`, stored UTC (I-13).
- Every user-owned row has `user_id TEXT NOT NULL REFERENCES users(id)` (I-10).
- Enumerations are `TEXT` with `CHECK` constraints, not PG `ENUM` types — adding a value
  to a PG enum requires a migration that cannot run inside a transaction alongside other
  DDL, which makes it a recurring nuisance for no benefit at this scale.

## Extensions

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;     -- fuzzy title/filename matching
```

## Identity and sessions

```sql
CREATE TABLE users (
    id              TEXT PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,              -- Argon2id
    display_name    TEXT NOT NULL,
    timezone        TEXT NOT NULL DEFAULT 'UTC',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
    id              TEXT PRIMARY KEY,           -- opaque; the cookie value is a hash of this
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      TEXT NOT NULL UNIQUE,       -- SHA-256 of the cookie value
    user_agent      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    revoked_at      TIMESTAMPTZ
);

CREATE INDEX sessions_user_active_idx
    ON sessions (user_id) WHERE revoked_at IS NULL;

CREATE TABLE push_subscriptions (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint        TEXT NOT NULL,
    p256dh          TEXT NOT NULL,
    auth            TEXT NOT NULL,
    device_label    TEXT,                       -- "iPhone PWA", "MacBook Safari"
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_success_at TIMESTAMPTZ,
    failure_count   INTEGER NOT NULL DEFAULT 0,
    UNIQUE (user_id, endpoint)
);
```

The session cookie carries a random token; the table stores only its hash, so a database
read does not yield usable session credentials.

## Job queue

```sql
CREATE TABLE jobs (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    queue           TEXT NOT NULL,              -- 'agent' | 'ingest' | 'poll' | 'maintenance'
    kind            TEXT NOT NULL,              -- 'agent.run', 'ingest.audio', 'poll.canvas', ...
    payload         JSONB NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued','claimed','running','succeeded','failed','cancelled')),
    priority        SMALLINT NOT NULL DEFAULT 100,   -- lower runs first
    run_after       TIMESTAMPTZ NOT NULL DEFAULT now(),
    attempts        INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 3,
    claimed_by      TEXT,                       -- worker instance id
    claimed_at      TIMESTAMPTZ,
    heartbeat_at    TIMESTAMPTZ,
    last_error      TEXT,
    idempotency_key TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ
);

-- The claim query's covering index. Partial, because only queued rows are ever claimed.
CREATE INDEX jobs_claim_idx
    ON jobs (queue, priority, run_after, id)
    WHERE status = 'queued';

-- Enqueue-once semantics for pollers: the same poll must not stack up.
CREATE UNIQUE INDEX jobs_idempotency_idx
    ON jobs (idempotency_key)
    WHERE idempotency_key IS NOT NULL
      AND status IN ('queued','claimed','running');

CREATE INDEX jobs_stale_idx
    ON jobs (heartbeat_at) WHERE status = 'running';
```

### The claim query

<!-- verbatim -->
```sql
-- Claims one job. SKIP LOCKED lets N workers run this concurrently without
-- blocking each other: a row locked by another worker is skipped, not waited on.
UPDATE jobs
SET status      = 'claimed',
    claimed_by  = :worker_id,
    claimed_at  = now(),
    heartbeat_at = now(),
    attempts    = attempts + 1
WHERE id = (
    SELECT id
    FROM jobs
    WHERE status = 'queued'
      AND queue  = :queue
      AND run_after <= now()
    ORDER BY priority, run_after, id
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING *;
```

### Reaping

A worker that dies mid-job leaves a row in `running` with a stale heartbeat. A
maintenance job returns those rows to `queued` when
`heartbeat_at < now() - :stale_after`, up to `max_attempts`. This is why the job is
*claimed then heartbeated* rather than simply deleted on start — the queue must be
recoverable after a container restart, which happens on every deploy.

### Wakeup

`NOTIFY athena_jobs, '<queue>'` is emitted by a trigger on insert. Workers `LISTEN` and
also poll every `poll_interval_s`. **The poll is the correctness guarantee** — `NOTIFY`
is lost if no session is listening at that moment (D-07).

## Documents — the vault registry

`documents` is a registry of vault files, not an index. It tells the ingestion worker what
has changed, gives conflict records and Canvas file mappings something to point at, and
records what has been handed to OpenViking. It holds no vectors and no chunk text.

```sql
CREATE TABLE documents (
    id              TEXT PRIMARY KEY,           -- ULID; matches vault frontmatter `id`
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    vault_path      TEXT NOT NULL,              -- relative to vault root
    viking_uri      TEXT,                       -- set once handed to OpenViking
    title           TEXT NOT NULL,
    source_type     TEXT NOT NULL
                    CHECK (source_type IN ('note','lecture_transcript','slide_deck',
                                           'canvas_file','reference','journal','memory')),
    content_date    DATE,                       -- frontmatter `date`; also determines the path
    course_slug     TEXT,
    tags            TEXT[] NOT NULL DEFAULT '{}',
    provenance      TEXT NOT NULL CHECK (provenance IN ('user','athena','mixed')),
    source_media    TEXT,
    frontmatter     JSONB NOT NULL DEFAULT '{}',
    content_hash    TEXT NOT NULL,              -- SHA-256 of the file body
    indexed_at      TIMESTAMPTZ,                -- last successful OpenViking submission
    index_error     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, vault_path)
);

CREATE INDEX documents_filter_idx
    ON documents (user_id, source_type, course_slug, content_date);
CREATE INDEX documents_stale_idx
    ON documents (user_id) WHERE indexed_at IS NULL;
CREATE INDEX documents_title_trgm_idx
    ON documents USING gin (title gin_trgm_ops);
```

`content_hash` still drives delta work, but the delta is now "does this file need
resubmitting to OpenViking," not "which chunks need re-embedding." Chunking is
OpenViking's concern.

`documents_stale_idx` is what the nightly catch-up job scans: anything with a null
`indexed_at` was written to the vault but never successfully indexed, which is the
expected state after an OpenViking outage (I-01 — the vault write is never blocked on the
index).

### Index submissions

```sql
CREATE TABLE index_runs (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    trigger         TEXT NOT NULL CHECK (trigger IN ('watch','manual','full_rebuild','ingest','catchup')),
    documents_seen  INTEGER NOT NULL DEFAULT 0,
    documents_sent  INTEGER NOT NULL DEFAULT 0,
    documents_skipped INTEGER NOT NULL DEFAULT 0,   -- hash unchanged
    documents_removed INTEGER NOT NULL DEFAULT 0,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    error           TEXT
);
```

`documents_skipped` is the metric proving delta submission works: reindexing an unchanged
vault should report `documents_sent = 0`.

## Source mirrors

```sql
CREATE TABLE email_accounts (
    id              TEXT PRIMARY KEY,           -- matches accounts.toml `id`
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    address         TEXT NOT NULL,
    provider        TEXT NOT NULL CHECK (provider IN ('gmail','imap')),
    last_sync_at    TIMESTAMPTZ,
    sync_cursor     TEXT,                       -- Gmail historyId / IMAP UIDVALIDITY:UID
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, address)
);

CREATE TABLE email_messages (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id      TEXT NOT NULL REFERENCES email_accounts(id) ON DELETE CASCADE,
    provider_id     TEXT NOT NULL,              -- Gmail message id / IMAP UID
    thread_key      TEXT NOT NULL,              -- Gmail threadId / normalised References header
    message_id_hdr  TEXT,                       -- RFC 5322 Message-ID, for reply threading
    from_address    TEXT NOT NULL,
    to_addresses    TEXT[] NOT NULL DEFAULT '{}',
    cc_addresses    TEXT[] NOT NULL DEFAULT '{}',
    subject         TEXT,
    body_text       TEXT,
    sent_at         TIMESTAMPTZ NOT NULL,
    labels          TEXT[] NOT NULL DEFAULT '{}',
    -- Deterministic pre-filter outcome (I-11). Set without any model call.
    prefilter       TEXT NOT NULL DEFAULT 'pending'
                    CHECK (prefilter IN ('pending','ignored','eligible')),
    prefilter_rule  TEXT,                       -- which rule decided, for debuggability
    -- Model triage outcome; only set for rows where prefilter='eligible'.
    triage          TEXT CHECK (triage IN ('no_action','needs_reply','calendar','informational')),
    triage_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (account_id, provider_id)
);

CREATE INDEX email_triage_queue_idx
    ON email_messages (user_id, sent_at DESC)
    WHERE prefilter = 'eligible' AND triage IS NULL;
CREATE INDEX email_thread_idx ON email_messages (user_id, thread_key, sent_at);
```

`prefilter_rule` exists because "why did Athena not tell me about this email" must be
answerable without re-running anything. The rule that suppressed it is on the row.

```sql
CREATE TABLE calendars (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider        TEXT NOT NULL CHECK (provider IN ('google','caldav')),
    provider_cal_id TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    writable        BOOLEAN NOT NULL DEFAULT FALSE,
    is_default      BOOLEAN NOT NULL DEFAULT FALSE,
    sync_cursor     TEXT,                       -- Google syncToken / CalDAV ctag
    UNIQUE (user_id, provider, provider_cal_id)
);

CREATE TABLE calendar_events (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    calendar_id     TEXT NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
    provider_ev_id  TEXT NOT NULL,
    summary         TEXT NOT NULL,
    description     TEXT,
    location        TEXT,
    starts_at       TIMESTAMPTZ NOT NULL,
    ends_at         TIMESTAMPTZ NOT NULL,
    all_day         BOOLEAN NOT NULL DEFAULT FALSE,
    -- Set when Athena created the event, so it can recognise and update its own rows.
    created_by_athena BOOLEAN NOT NULL DEFAULT FALSE,
    origin_kind     TEXT,                       -- 'canvas_due_date' | 'email' | 'prompt'
    origin_ref      TEXT,                       -- canvas_assignments.id, email_messages.id, ...
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (calendar_id, provider_ev_id)
);

CREATE INDEX calendar_events_window_idx
    ON calendar_events (user_id, starts_at);
CREATE UNIQUE INDEX calendar_events_origin_idx
    ON calendar_events (user_id, origin_kind, origin_ref)
    WHERE origin_kind IS NOT NULL;
```

`calendar_events_origin_idx` is what stops Athena creating a second event every time it
re-reads the same Canvas due date. Idempotency at the data layer, not in the agent's
judgment.

```sql
CREATE TABLE canvas_courses (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    canvas_id       BIGINT NOT NULL,
    name            TEXT NOT NULL,
    course_code     TEXT NOT NULL,
    slug            TEXT NOT NULL,              -- vault folder name
    term            TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (user_id, canvas_id)
);

CREATE TABLE canvas_assignments (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id       TEXT NOT NULL REFERENCES canvas_courses(id) ON DELETE CASCADE,
    canvas_id       BIGINT NOT NULL,
    name            TEXT NOT NULL,
    description_html TEXT,
    due_at          TIMESTAMPTZ,
    points_possible NUMERIC,
    submission_types TEXT[] NOT NULL DEFAULT '{}',
    html_url        TEXT,
    -- Previous observed due date, so a change is detectable without an audit scan.
    previous_due_at TIMESTAMPTZ,
    due_changed_at  TIMESTAMPTZ,
    workflow_state  TEXT,
    has_submitted   BOOLEAN NOT NULL DEFAULT FALSE,
    vault_path      TEXT,                       -- the assignment note
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, canvas_id)
);

CREATE INDEX canvas_due_idx
    ON canvas_assignments (user_id, due_at)
    WHERE due_at IS NOT NULL AND has_submitted = FALSE;

CREATE TABLE canvas_files (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id       TEXT NOT NULL REFERENCES canvas_courses(id) ON DELETE CASCADE,
    assignment_id   TEXT REFERENCES canvas_assignments(id) ON DELETE SET NULL,
    canvas_id       BIGINT NOT NULL,
    filename        TEXT NOT NULL,
    content_type    TEXT,
    size_bytes      BIGINT,
    canvas_updated_at TIMESTAMPTZ,
    document_id     TEXT REFERENCES documents(id) ON DELETE SET NULL,
    download_state  TEXT NOT NULL DEFAULT 'pending'
                    CHECK (download_state IN ('pending','downloaded','converted','failed','skipped')),
    UNIQUE (user_id, canvas_id)
);
```

## Approvals and effects

```sql
CREATE TABLE approvals (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    run_id          TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    thread_id       TEXT NOT NULL,
    tool_call_id    TEXT NOT NULL,
    tool_name       TEXT NOT NULL,
    tool_args       JSONB NOT NULL,
    summary         TEXT NOT NULL,              -- human-readable, rendered in the UI and push
    allowed_decisions TEXT[] NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','approved','rejected','edited','expired','superseded')),
    decision_args   JSONB,                      -- edited arguments, when status='edited'
    decided_at      TIMESTAMPTZ,
    decided_by      TEXT REFERENCES users(id),
    auto_approved   BOOLEAN NOT NULL DEFAULT FALSE,
    auto_rule       TEXT,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, tool_call_id)
);

CREATE INDEX approvals_pending_idx
    ON approvals (user_id, created_at DESC) WHERE status = 'pending';
CREATE INDEX approvals_expiry_idx
    ON approvals (expires_at) WHERE status = 'pending';
```

```sql
CREATE TABLE effects (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    run_id          TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    tool_call_id    TEXT NOT NULL,
    approval_id     TEXT REFERENCES approvals(id),
    kind            TEXT NOT NULL,              -- 'email.send', 'calendar.create', ...
    request         JSONB NOT NULL,             -- exactly what will be sent
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','executing','succeeded','failed')),
    external_id     TEXT,                       -- provider's id for the created thing
    response        JSONB,
    error           TEXT,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, tool_call_id)               -- I-08: replay cannot repeat an effect
);
```

The `UNIQUE (run_id, tool_call_id)` on `effects` is the persist-before-execute guarantee
(I-08) expressed as a constraint. The executor's contract:

1. Open a transaction. Insert the `effects` row as `pending`. If the insert conflicts, an
   effect for this tool call already exists — read it and return its recorded outcome
   instead of calling out. Commit.
2. Call the external system.
3. Update to `succeeded` or `failed` with the response. Commit.

A crash between 1 and 3 leaves a `pending` row; the reconciler surfaces it to the owner
rather than guessing, because "did the email send" cannot be safely inferred.

## Runs, threads, and traces

```sql
CREATE TABLE threads (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL CHECK (kind IN ('chat','automation','ingest')),
    title           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE runs (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id       TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    job_id          TEXT REFERENCES jobs(id),
    trigger         TEXT NOT NULL,              -- 'user','schedule','poll','approval_resume'
    status          TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued','running','waiting_approval','succeeded','failed','cancelled')),
    input           JSONB,
    output          JSONB,
    model_calls     INTEGER NOT NULL DEFAULT 0,
    tool_calls      INTEGER NOT NULL DEFAULT 0,
    prompt_tokens   INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX runs_thread_idx ON runs (thread_id, created_at DESC);
CREATE INDEX runs_waiting_idx ON runs (user_id) WHERE status = 'waiting_approval';

CREATE TABLE run_events (
    id              BIGSERIAL PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,
    kind            TEXT NOT NULL,              -- 'token','tool_call','tool_result','interrupt','error'
    payload         JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, seq)
);
```

`run_events` is the SSE replay log: a browser that reconnects mid-run resumes from its
last `seq` rather than losing the stream. It is also the trace viewer's data source.
Retention is configurable; events for completed runs are pruned by a maintenance job.

## Notifications, reminders, audit

```sql
CREATE TABLE notifications (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category        TEXT NOT NULL,              -- 'approval','reminder','digest','error'
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,
    link            TEXT,                       -- in-app deep link
    ref_kind        TEXT,
    ref_id          TEXT,
    delivered_at    TIMESTAMPTZ,
    read_at         TIMESTAMPTZ,
    push_attempts   INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX notifications_unread_idx
    ON notifications (user_id, created_at DESC) WHERE read_at IS NULL;

CREATE TABLE reminders (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject_kind    TEXT NOT NULL,              -- 'canvas_assignment','calendar_event'
    subject_id      TEXT NOT NULL,
    rule_id         TEXT NOT NULL,              -- which reminders.toml rule produced this
    fire_at         TIMESTAMPTZ NOT NULL,
    fired_at        TIMESTAMPTZ,
    cancelled_at    TIMESTAMPTZ,
    UNIQUE (user_id, subject_kind, subject_id, rule_id)
);

CREATE INDEX reminders_due_idx
    ON reminders (fire_at) WHERE fired_at IS NULL AND cancelled_at IS NULL;

CREATE TABLE audit_log (
    id              BIGSERIAL PRIMARY KEY,
    user_id         TEXT REFERENCES users(id) ON DELETE SET NULL,
    actor           TEXT NOT NULL,              -- 'user','agent','scheduler','system'
    action          TEXT NOT NULL,
    subject_kind    TEXT,
    subject_id      TEXT,
    detail          JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX audit_log_time_idx ON audit_log (created_at DESC);
CREATE INDEX audit_log_subject_idx ON audit_log (subject_kind, subject_id);
```

The `reminders` unique constraint is why a reminder does not fire twice when a poll
re-observes the same assignment: the rule's output for a given subject is a row, not an
event, and re-computing it is an upsert.

`audit_log.detail` MUST NOT contain secrets or full message bodies — it records what
happened and to which entity, not the content. Content lives in the source tables.

## Ingestion tracking

```sql
CREATE TABLE ingestions (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source          TEXT NOT NULL CHECK (source IN ('upload','canvas','watch','email')),
    original_name   TEXT,
    media_path      TEXT,                       -- vault-relative, under media/
    mime_type       TEXT,
    size_bytes      BIGINT,
    declared_frontmatter JSONB NOT NULL DEFAULT '{}',   -- what the owner supplied
    inferred_frontmatter JSONB NOT NULL DEFAULT '{}',   -- what Athena derived
    document_id     TEXT REFERENCES documents(id) ON DELETE SET NULL,
    stage           TEXT NOT NULL DEFAULT 'received'
                    CHECK (stage IN ('received','converting','converted','indexing','done','failed')),
    progress        JSONB NOT NULL DEFAULT '{}',   -- e.g. {"pages_done": 40, "pages_total": 60}
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ingestion_conflicts (
    id              TEXT PRIMARY KEY,
    ingestion_id    TEXT NOT NULL REFERENCES ingestions(id) ON DELETE CASCADE,
    field           TEXT NOT NULL,
    declared_value  TEXT,
    inferred_value  TEXT,
    resolution      TEXT NOT NULL DEFAULT 'kept_declared'
                    CHECK (resolution IN ('kept_declared','used_inferred','unresolved')),
    resolved_at     TIMESTAMPTZ
);
```

`progress` carries per-page checkpointing for PDF conversion (D-12), which is what lets a
60-page deck that failed at page 40 resume rather than restart.

## Migrations

Alembic. Rules:

- Every migration has a working `downgrade()`. A migration that cannot be reversed must
  say so explicitly with a raised exception and a comment explaining why.
- Data migrations are separate revisions from schema migrations.
- No migration may drop a column in the same release that stops writing to it. Two
  releases: stop writing, then drop.
- A migration that would rebuild the index does not do so. It marks documents
  `indexed_at = NULL` and lets the indexer catch up, so the migration itself stays fast.
