# Phase 12 — Write paths

**Objective.** Email send and reply, calendar create/update/delete — every one behind an
approval, every one idempotent, every one proven to be blocked by rejection.

**Preconditions.** Phase 11 gate green. Phase 03's subagent interrupt tests
(`approve`, `edit`, **and** `reject`) passing on the pinned `deepagents` version.

**This is the highest-risk phase.** Everything here can affect the outside world.

---

## Steps

### 1. Effect declarations first

Before writing any tool, declare each in the effect registry and add its rule to
`config/approvals.toml`. The startup assertion (I-03) then fails until the rule exists,
which is the desired ordering: the guard precedes the capability.

### 2. Email write tools

`email_send_message`, `email_reply`.

- Idempotency key is the `tool_call_id`, passed by the executor. A retry after a timeout
  must not send twice.
- `email_reply` sets `In-Reply-To` to the parent's `Message-ID` and appends it to
  `References`. Without this the reply starts a new thread in the recipient's client.
- Attachments are out of MVP scope; the tool rejects them explicitly rather than ignoring
  them.
- SMTP path uses submission with STARTTLS and verifies the certificate.

### 3. Calendar write tools

`calendar_create_event`, `calendar_update_event`, `calendar_delete_event`.

- `create` takes `origin_kind`/`origin_ref` and checks the partial unique index before
  creating. Re-observing a Canvas due date updates rather than duplicating — idempotency
  at the data layer, not in the agent's memory.
- CalDAV writes use the Athena ULID as the iCalendar UID, so the mapping is bidirectional
  with no lookup table.
- CalDAV updates require `If-Match` with the stored ETag. Without it, edits made on the
  owner's phone are silently overwritten.
- All-day events use `DATE`, not `DATE-TIME`; mixing them renders events an hour off in
  some clients.
- **Recurring series: refuse.** `calendar_update_event` and `calendar_delete_event` return
  a structured error on a recurring event, and `create` never produces one. Half-correct
  `RRULE`/`RECURRENCE-ID` handling silently corrupts a calendar, and correct handling is
  more than this MVP is buying.
- `delete` allows only `approve`/`reject` — no silent edit on a destructive action.

### 4. Executor integration

Every write tool routes through `execute_effect` (I-08). The `effects` unique constraint
on `(run_id, tool_call_id)` is what makes replay safe.

### 5. Reconciler

A maintenance job surfacing `effects` rows stuck in `pending` — the crash-between-persist-
and-execute case. It **does not guess**. It raises a notification asking the owner to
check whether the mail was sent. Guessing wrong in either direction is bad, and there is
no way to know.

### 6. Email drafter subagent

Given a thread and retrieved context, produce a draft. Its output is the argument to
`email_reply`, which interrupts. The subagent explicitly declares its interrupt rules
rather than relying on inheritance (D-01's trap).

### 7. Read-only flag off

`ATHENA_MCP_READ_ONLY` becomes configurable and defaults to **on**. Turning it off is a
deliberate deployment act, and `just doctor` reports its state prominently.

---

## Files produced

```
src/athena/mcp/email/write.py
src/athena/mcp/calendar/write.py
src/athena/agent/subagents/email_drafter.py
src/athena/automations/reconciler.py
prompts/email_drafter.md
tests/acceptance/test_phase_12_write_paths.py
tests/acceptance/test_phase_12_injection.py
```

## Tests required

### The boundary

1. Every write tool interrupts. Parametrized over all five; **failing to interrupt is a
   release blocker.**
2. Reject → the effect never executes. **Asserted at the fake transport, and by the
   absence of an `effects` row** — not at a mock's return value. A mock configured to
   raise would pass even if the code called it and swallowed the error.
3. Approve → executes exactly once.
4. Edit → executes with edited arguments.
5. All four, **from inside the `email_drafter` subagent**.
6. A write tool with no approval rule prevents startup.
7. Read-only mode: write tools absent from `tools/list`.

### Idempotency and durability

8. The same `tool_call_id` executed twice produces one effect and one send.
9. Crash between persist and execute leaves a `pending` row; the reconciler surfaces it
   and does not retry automatically.
10. Resuming a run after a full stack restart does not re-execute a completed effect.
11. Re-observing the same Canvas due date updates the existing event; no duplicate.

### Provider correctness

12. `email_reply` sets `In-Reply-To` and `References` correctly (assert on the generated
    MIME).
13. CalDAV update without a matching ETag fails rather than overwriting.
14. A recurring event update returns the structured refusal.
15. All-day events use `DATE` values.

### Injection

16. Parametrized over an injection corpus embedded in email bodies, Canvas assignment
    descriptions, and PDF-derived text. **The assertion is never that the model refused —
    it is that no effect executed without an approval**, whatever the model did.
17. An injection that induces a send attempt still produces an approval whose summary
    accurately describes the attempted action.

## Exit gate

- All tests pass.
- **Manual, with a throwaway address:** ask Athena to email it. Confirm the approval
  arrives on the phone. Reject it; confirm nothing arrives at the address. Repeat and
  approve; confirm it arrives, correctly threaded.
- Manual: create a calendar event through Athena; confirm it appears in both Google and
  Apple Calendar as expected.
- Manual: run the full injection corpus against a live-but-throwaway configuration and
  confirm no unapproved effect occurs.
- Re-read [`13-security.md`](../13-security.md) with the full tool surface in hand and
  re-review every rule in `config/approvals.toml`. **A rule set that fenced three tools
  correctly may not fence eight.**
