# Phase 13 — Scheduler, reminders, digest

**Objective.** The daemon becomes autonomous: scheduled polls, the reminder engine, quiet
hours, escalation, and the morning digest.

**Preconditions.** Phase 12 gate green.

Read [`11-automations.md`](../11-automations.md) in full first.

---

## Steps

### 1. Dependencies

```bash
uv add apscheduler
```

### 2. Scheduler service

`src/athena/scheduler/` — APScheduler with `SQLAlchemyJobStore` in Postgres, so schedules
survive restarts and the container is stateless.

**The scheduler enqueues and returns.** It never does work. A slow poll must not delay the
next trigger, and the container must be restartable at any moment without losing in-flight
work.

Every poll enqueues with idempotency key `poll:<kind>:<window>`, so a slow poll does not
stack up behind itself.

`misfire_grace_time` from config: after the machine has been asleep or the stack down, a
missed poll should run once on recovery, not N times for N missed windows.

### 3. Reminder engine

`src/athena/automations/reminders.py`.

Reminders are **rows, not events**. The rules are evaluated into `reminders` rows by
upsert against `(user_id, subject_kind, subject_id, rule_id)`, so re-running the rules
after a poll is idempotent and a reminder never fires twice.

Rule evaluation is fully deterministic (I-11): lead-time arithmetic, `skip_if`
predicates, `points_possible` overrides, `after_due` escalation with `stop_after`.

### 4. Fire loop

Per [`11-automations.md`](../11-automations.md#fire-loop). The three properties:

- **Re-check the skip condition at fire time.** An assignment submitted since the reminder
  was scheduled must not fire.
- **Quiet hours defer, never drop.** Dropping loses information; firing at 3am trains you
  to ignore notifications, which breaks the approval path too.
- **The notification row and `fired_at` commit in one transaction.** No state where a
  reminder is marked fired but was never announced.

### 5. Due-date change handling

`assignment_due_changed` cancels the assignment's outstanding reminders, recomputes them
against the new date, and fires an immediate notification. A moved deadline is the single
most valuable signal the system produces.

### 6. Cross-reference pass and digest

Deterministic assembly of the facts first: what is due in the window, what is on the
calendar, which flagged emails are unanswered, which approvals are pending.

If the assembled set exceeds the configured threshold, an agent run writes the digest
prose. **The facts are passed in; the model never queries for them**, so it cannot miss
one. The model orders and phrases; it does not decide what is due.

`skip_if_empty` so a quiet morning produces no notification.

### 7. Maintenance jobs

`expire_approvals`, `reap_stale_jobs`, `reindex_vault` (nightly catch-up for anything the
watcher missed), `prune_run_events`, `backup` if configured.

---

## Files produced

```
src/athena/scheduler/{__init__,service,jobs,__main__}.py
src/athena/automations/{reminders,digest,crossref,maintenance}.py
tests/integration/scheduler/**
tests/acceptance/test_phase_13_reminders.py
```

## Tests required

1. Lead-time rules produce the right `fire_at` for each configured lead time.
2. `skip_if` prevents scheduling, and also prevents firing when the condition becomes true
   after scheduling.
3. Quiet hours defer to the end of the window; the reminder is not lost.
4. A DST transition inside a lead-time window produces the correct local fire time (I-13).
5. Overdue escalation fires the configured number of times and then stops.
6. Due-date change cancels and recomputes; no stale reminder survives.
7. Re-running rule evaluation is idempotent — no duplicate rows, no duplicate fires.
8. Notification and `fired_at` commit together; a simulated failure between them leaves
   neither.
9. Digest assembles the correct facts; with a patched model, the assembled input contains
   every due item.
10. `skip_if_empty` suppresses an empty digest.
11. Scheduler restart preserves jobs (they are in Postgres).
12. Misfire after downtime runs once, not N times.
13. Reminder rules make no model call (patch `model_for_role` to raise).
14. Concurrent fire loops do not double-fire (`SKIP LOCKED` over `reminders_due_idx`).

## Exit gate

- All tests pass.
- **Run the daemon for one full week against real accounts.** Record: reminders fired
  versus expected, false positives, missed items, approvals raised, and how many were
  still pending at expiry.
- Confirm no reminder fired during quiet hours.
- Confirm the morning digest is accurate on at least five consecutive days, checked by
  hand against Canvas and the calendar.

The week-long soak is the gate. Scheduling bugs — timezone edges, misfire storms after
sleep, duplicate fires — do not appear in a test suite; they appear on the fourth day.
