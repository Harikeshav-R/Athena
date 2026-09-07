# Phase 02 — Postgres, schema, migrations, job queue

**Objective.** The full schema from [`06-data-model.md`](../06-data-model.md), Alembic
migrations, repositories, and a working job queue with claim, heartbeat, reaping, and
`LISTEN`/`NOTIFY` wakeup.

**Preconditions.** Phase 01 gate green.

---

## Steps

### 1. Dependencies

```bash
uv add sqlalchemy[asyncio] asyncpg alembic python-ulid
uv add --group dev testcontainers[postgres]
```

### 2. Dev infrastructure

`docker/compose.dev.yml` with `postgres` (image `postgres:17`) only. Local
development runs the application natively against containerized infrastructure; full
containerization is Phase 15.

### 3. Engine and session management

`src/athena/db/engine.py`:

- Async engine from `config.database.url`.
- `async_sessionmaker` with `expire_on_commit=False`.
- An `async_session()` context manager that commits on clean exit and rolls back on
  exception.
- Pool sizing from config.

### 4. Models

SQLAlchemy 2.0 declarative with `Mapped[...]` annotations, mirroring
[`06-data-model.md`](../06-data-model.md) exactly. Where the document and the models
disagree, the document is wrong and gets updated in the same commit.

No vector columns — retrieval is OpenViking's (D-02, D-04). If you find yourself adding a
`chunks` table, stop: you are working from a stale reference.

### 5. Migrations

```bash
uv run alembic init -t async migrations
```

The initial migration creates everything. Rules from
[`06-data-model.md`](../06-data-model.md#migrations) apply from here on.

### 6. Repositories

One module per aggregate under `src/athena/db/repositories/`. Every function takes
`user_id` as a required keyword parameter (I-10). No defaults, no implicit "current user."

### 7. The job queue

`src/athena/queue/`:

```python
async def enqueue(
    session,
    *,
    user_id: str,
    queue: str,
    kind: str,
    payload: dict,
    priority: int = 100,
    run_after: datetime | None = None,
    idempotency_key: str | None = None,
) -> Job: ...


async def claim(session, *, queue: str, worker_id: str) -> Job | None: ...


async def heartbeat(session, *, job_id: str) -> None: ...


async def complete(session, *, job_id: str, result: dict | None = None) -> None: ...


async def fail(session, *, job_id: str, error: str, retry: bool = True) -> None: ...


async def reap_stale(session, *, stale_after: timedelta) -> int: ...
```

`claim` uses the verbatim SQL from
[`06-data-model.md`](../06-data-model.md#the-claim-query). Do not rewrite it into ORM
constructs — `FOR UPDATE SKIP LOCKED` inside a subquery driving an `UPDATE` is precise and
the ORM translation is not obviously equivalent.

### 8. Wakeup

- A trigger on `jobs` insert emitting `NOTIFY athena_jobs, '<queue>'`.
- A listener holding a dedicated `asyncpg` connection.
- **The worker loop polls on `config.queue.poll_interval_s` regardless of notifications.**
  `NOTIFY` is lost if no session is listening; the poll is the correctness guarantee
  (D-07). A worker that only listens works in development and stalls in production.

### 9. Worker skeleton

`src/athena/worker/` — a loop that claims, dispatches by `kind` through a handler
registry, heartbeats on an interval while the handler runs, and completes or fails. No
handlers yet beyond a test one.

Graceful shutdown on `SIGTERM`: stop claiming, finish the current job, exit. Docker sends
`SIGTERM` on every restart, and a worker that dies mid-job leaves a row to reap.

---

## Files produced

```
docker/compose.dev.yml
migrations/**
src/athena/db/{engine,models,repositories}/**
src/athena/queue/{__init__,queue,listener}.py
src/athena/worker/{__init__,loop,registry,__main__}.py
tests/integration/db/**
tests/integration/queue/**
```

## Tests required

1. `alembic upgrade head` then `downgrade base` cleanly, on an empty database.
2. Every timestamp column is `TIMESTAMPTZ` (I-13), asserted by querying
   `information_schema`.
3. Every user-owned table has a `user_id` FK (I-10), asserted the same way.
4. **Concurrency:** N workers claiming from a queue of M jobs process each exactly once,
   with no duplicates and no skips. This test **must** use committed data (per-schema
   fixture, not the rollback fixture) or it is vacuous — see
   [`15-testing.md`](../15-testing.md#postgres-in-tests).
5. Idempotency key prevents a duplicate enqueue while an earlier job is in flight, and
   permits one after it completes.
6. `reap_stale` returns a job whose heartbeat lapsed, and respects `max_attempts`.
7. `NOTIFY` wakes a listening worker faster than the poll interval.
8. **A worker with the listener disabled still processes jobs**, at poll cadence. This is
   the test that stops someone from deleting the poll as redundant.
9. `SIGTERM` completes the in-flight job before exiting.

## Exit gate

- All tests pass, including the concurrency test at ≥4 workers and ≥200 jobs.
- 100% coverage on `src/athena/db` and `src/athena/queue`.
- `just migrate` works against a fresh container.
