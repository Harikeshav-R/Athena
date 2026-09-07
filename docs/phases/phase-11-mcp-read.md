# Phase 11 — MCP servers, read-only

**Objective.** Email, calendar, and Canvas readable through three MCP servers. **No write
tool exists in any of them** — not disabled, absent.

**Preconditions.** Phase 10 gate green.

Read [`10-integrations.md`](../10-integrations.md) in full first.

---

## Steps

### 1. Dependencies

```bash
uv add mcp httpx google-auth google-auth-oauthlib google-api-python-client caldav icalendar
```

### 2. Server skeleton

`src/athena/mcp/base.py` — shared MCP server construction, streamable HTTP transport,
structured errors, log redaction, and the `ATHENA_MCP_READ_ONLY` flag.

**Under read-only, write tools are not registered at all.** Not registered-and-refusing.
A tool absent from `tools/list` cannot be called, and the model cannot be talked into
calling something that does not exist.

In this phase the flag is forced on and the write tools do not yet exist.

### 3. Email server

`EmailProvider` protocol plus three adapters (Gmail API, IMAP, generic IMAP).

Read tools: `email_list_messages`, `email_get_message`, `email_get_thread`,
`email_search`.

`email_list_messages` returns headers and previews, not bodies (I-09's reasoning applied
to tool results — a listing of fifty full messages exhausts context and buys nothing).

Cursor handling:

- Gmail `historyId`, **with a full-relist fallback** when the API rejects a stale id.
  Gmail expires history after roughly a week; an account that has not synced over a break
  will hit this, and without the fallback it hard-fails.
- IMAP `UIDVALIDITY:UIDNEXT`. **A `UIDVALIDITY` change invalidates every stored UID** and
  requires a full relist. iCloud does change it.

Forward-only from install (L4): the first sync records the current cursor and ingests
nothing historical.

### 4. Calendar server

Google Calendar API and CalDAV adapters. Read tools: `calendar_list_calendars`,
`calendar_list_events` (time window is a required parameter), `calendar_get_event`.

CalDAV reading: `PROPFIND` for calendar discovery, `REPORT` with a time-range filter for
events. Store the ETag on every event row now, even though it is only needed for writes
in Phase 12 — capturing it later means a full resync.

### 5. Canvas server

All read tools from [`10-integrations.md`](../10-integrations.md#athena-mcp-canvas).

Specifics that will bite otherwise:

- Pagination is `Link` headers; follow `rel="next"` until absent.
- Rate limiting via `X-Rate-Limit-Remaining`; back off before zero, not after a 403.
- **Read the assignment override that applies to the owner's enrolment**, not the base
  `due_at`. A section-specific extension is otherwise invisible, and a wrong due date is
  worse than no due date.
- Filter to the current term, or years of concluded courses come back.

**No Canvas write tool is ever added, in any phase** — this is a non-goal, not a phase
boundary.

### 6. MCP client wiring

`src/athena/agent/mcp_client.py` — connect to the three servers, load their tools, merge
into the agent's tool list. Connection failures are surfaced as a degraded-capability
notification, not swallowed (I-12).

### 7. Pollers

`src/athena/automations/pollers/` for Canvas, email, and calendar, per
[`11-automations.md`](../11-automations.md#pollers).

Deterministic throughout (I-11). The Canvas poller emits `assignment_discovered`,
`assignment_due_changed`, `assignment_removed`, `file_available` by comparison, with no
model call anywhere in it.

### 8. Email pre-filter

`src/athena/automations/prefilter.py` — the rule engine from
[`07-ingestion.md`](../07-ingestion.md#the-deterministic-pre-filter). Every rule has an
`id` recorded on the message, so "why did Athena not surface this email" is answerable by
reading one column.

### 9. Triage

Model call on `prefilter = 'eligible'` messages only, producing the four-way enum plus a
confidence. Cheapest role (D-10).

---

## Files produced

```
src/athena/mcp/{__init__,base,__main__}.py
src/athena/mcp/email/{server,provider,gmail,imap}.py
src/athena/mcp/calendar/{server,provider,google,caldav}.py
src/athena/mcp/canvas/{server,client}.py
src/athena/agent/mcp_client.py
src/athena/automations/{prefilter,triage}.py
src/athena/automations/pollers/{canvas,email,calendar}.py
tests/contract/**
tests/fixtures/{gmail,imap,caldav,google_calendar,canvas}/**
```

## Tests required

1. **No write tool is registered** by any server. Assert against `tools/list` for all
   three — this is the phase's defining property.
2. Contract tests per provider against recorded fixtures.
3. Gmail: stale `historyId` triggers the full-relist fallback.
4. IMAP: `UIDVALIDITY` change triggers a full relist.
5. Canvas: pagination follows every `Link` page.
6. Canvas: a section override is preferred over the base `due_at`.
7. Canvas: concluded-term courses are excluded.
8. Poller diffing: due-date change emits `assignment_due_changed` with both values.
9. Poller diffing: an unchanged poll emits nothing.
10. **Pollers make no model call.** Assert by patching `model_for_role` to raise (I-11).
11. Prefilter: each rule form matches correctly, and `prefilter_rule` records which one
    decided.
12. Prefilter: rules are evaluated in order and the first match wins.
13. Triage runs only on `eligible` messages.
14. No credential appears in any tool result, including error paths — parametrized over
    every tool with a forced failure.
15. `src/athena/automations/` does not import the agent graph or a model client, asserted
    by import-graph analysis (I-11).

## Exit gate

- All tests pass.
- Against real accounts, manually and read-only: list recent mail from both accounts,
  list this week's calendar events from both calendars, list current-term Canvas courses
  and assignments with correct due dates.
- Ingest one real Canvas assignment's attached files end to end.
- Confirm `tools/list` on all three servers contains no write tool.
