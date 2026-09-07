# Phase 08 — FastAPI backend and authentication

**Objective.** An authenticated HTTP API with SSE streaming, exposing chat, retrieval,
vault, ingestion, jobs, and config. No UI yet.

**Preconditions.** Phase 07 gate green.

---

## Steps

### 1. Dependencies

```bash
uv add fastapi uvicorn[standard] argon2-cffi python-multipart itsdangerous
```

### 2. Application

`src/athena/api/app.py` — app factory, lifespan managing the engine, config watcher, and
graceful shutdown.

Middleware order, which matters:

1. Correlation ID (must be first so everything downstream logs it)
2. Request logging
3. Session authentication
4. Rate limiting
5. Exception handling (must be outermost to catch everything)

### 3. Authentication

`src/athena/api/auth.py`:

- Argon2id via `argon2-cffi`, parameters from config.
- Session cookie holding a random token; `sessions` stores only its SHA-256.
- `HttpOnly`, `Secure`, `SameSite=Strict`.
- Sliding expiry with an absolute maximum.
- Login rate-limited per username **and** per source address, with constant-time
  comparison and a fixed minimum response time so timing does not reveal whether a
  username exists.
- `athena user create` CLI command for bootstrapping the first user. There is no
  self-registration.

### 4. Routers

Per [`12-web-ui.md`](../12-web-ui.md#api-surface). One module per resource group. Every
handler takes the authenticated user and passes `user_id` explicitly to repositories
(I-10) — no request-scoped implicit user.

### 5. SSE

`src/athena/api/streaming.py`:

- `text/event-stream` from `run_events`, polling or `LISTEN`-driven.
- `Last-Event-ID` honoured, resuming from that `seq`. This is what makes an iOS browser
  that backgrounds mid-answer recover instead of losing it.
- Heartbeat comments on an interval so proxies do not time the connection out.
- Client disconnect must not cancel the run — the run continues and the client can
  reconnect and replay. A backgrounded phone must not kill work.

### 6. Uploads

Streamed to disk in chunks, never buffered — lossless 90-minute audio is large. Size
limit from config. Content type from magic bytes. The temp file is moved into `media/`
only after the `ingestions` row commits.

### 7. Config endpoint

Read-only (J4). Renders the live config with every `*_env` field showing the variable
name and never a value, alongside the JSON Schema for inline documentation.

A test asserts no secret value appears in the response for a config referencing a set
variable.

### 8. Error handling

A global handler returning `{"error": {"code", "message", "correlation_id"}}`. Details go
to logs. No stack traces, no internal paths, no secret values in any response.

---

## Files produced

```
src/athena/api/{__init__,app,auth,streaming,errors,dependencies,__main__}.py
src/athena/api/routers/{auth,threads,runs,approvals,ingestions,vault,search,config,jobs,notifications,push}.py
src/athena/cli.py
tests/integration/api/**
```

## Tests required

1. Unauthenticated request to every protected route → 401.
2. Login succeeds; cookie has all three security attributes.
3. Wrong password → 401, and response time is within tolerance of the success path.
4. Login rate limiting engages per username and per address.
5. Session expiry and revocation both invalidate.
6. **`/api/vault/file` rejects the full traversal matrix from Phase 04.** The HTTP layer
   needs the same fence as the tools, and it is easy to forget.
7. SSE delivers events in order; `Last-Event-ID` resumes from the right `seq`.
8. Client disconnect does not cancel the run; reconnect replays.
9. Upload of a large file streams without loading it into memory (assert peak RSS).
10. Upload with a mismatched extension is routed by sniffed content type.
11. `/api/config` contains no secret values.
12. Errors return a correlation id and no internals.
13. A second user cannot read the first user's threads, runs, approvals, documents, or
    ingestions (I-10) — parametrized over every read route.

## Exit gate

- All tests pass, 100% coverage on `src/athena/api`.
- Manual: log in with `curl`, ask a question, watch the SSE stream, get a cited answer.
- Manual: kill the client mid-stream, reconnect with `Last-Event-ID`, receive the rest.
