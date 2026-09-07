# 11 — Automations

Everything here obeys I-11: polling, diffing, and date arithmetic are plain Python; the
LLM is invoked only where the answer is genuinely contestable.

`src/athena/automations/` MUST NOT import the agent graph or a model client. When it needs
judgment it enqueues a run. A test asserts this import boundary.

## Scheduler

APScheduler in `athena-scheduler`, with `SQLAlchemyJobStore` in Postgres so schedules
survive restarts and the container is stateless.

The scheduler **enqueues and returns**. It never does work. This keeps a slow poll from
delaying the next trigger and means the scheduler container can be restarted at any
moment without losing in-flight work.

```toml
# config/schedules.toml
timezone = "America/New_York"

[jobs.poll_canvas]
enabled  = true
trigger  = "interval"
minutes  = 30
jitter_s = 120          # avoid a thundering herd against Canvas on the hour

[jobs.poll_email]
enabled  = true
trigger  = "interval"
minutes  = 5

[jobs.poll_calendar]
enabled  = true
trigger  = "interval"
minutes  = 15

[jobs.fire_reminders]
enabled  = true
trigger  = "interval"
minutes  = 1            # the tick that fires due reminders; cheap, no external calls

[jobs.daily_digest]
enabled  = true
trigger  = "cron"
hour     = 7
minute   = 30

[jobs.expire_approvals]
enabled  = true
trigger  = "interval"
minutes  = 5

[jobs.reap_stale_jobs]
enabled  = true
trigger  = "interval"
minutes  = 2

[jobs.reindex_vault]
enabled  = true
trigger  = "cron"
hour     = 3
minute   = 0            # catch anything the watcher missed
```

Every poll job is enqueued with an idempotency key of `poll:<kind>:<window>`, so a slow
poll does not stack up behind itself (see the partial unique index on `jobs`).

## Pollers

Each poller is the same shape:

```
fetch (via MCP, read-only)
  → normalise
  → upsert into the mirror table
  → compute a diff against what was there
  → emit domain events
```

### Canvas poller

```python
def poll_canvas(user_id: str) -> PollReport:
    """Refresh courses, assignments, and attached files.

    Emits, deterministically:
      - assignment_discovered   (first_seen_at just set)
      - assignment_due_changed  (due_at != previous_due_at)
      - assignment_removed      (present before, absent now)
      - file_available          (new or updated canvas_files row)

    No model call anywhere in this function. "Has this due date moved" is a
    comparison (I-11). A due-date change is the single most valuable signal the
    system produces and it must not depend on an LLM being available or
    consistent.
    """
```

`assignment_due_changed` writes `previous_due_at` and `due_changed_at`, which drives both
a notification and a recomputation of that assignment's reminders.

### Email poller

Fetches new messages since the cursor, applies the deterministic pre-filter
([`07-ingestion.md`](07-ingestion.md#the-deterministic-pre-filter)), and stores rows. Only
`prefilter = 'eligible'` messages are enqueued for model triage, and only
`triage in ('needs_reply', 'calendar')` produce an agent run.

The funnel matters on free-tier models: full inbox → pre-filter → triage → agent. Each
stage is cheaper than the next by roughly an order of magnitude.

### Calendar poller

Google `syncToken`, CalDAV `ctag`/ETag. Its main job is keeping `calendar_events` current
so the reminder engine and the cross-reference pass see real availability, and so Athena
recognises its own events (`created_by_athena`) rather than treating them as new.

## Reminder engine

Reminders are **rows, not events** (see the unique constraint in
[`06-data-model.md`](06-data-model.md)). Re-running the rules is an upsert, so a poll that
re-observes the same assignment does not produce a second reminder.

```toml
# config/reminders.toml
[general]
timezone        = "America/New_York"
quiet_hours     = { start = "22:00", end = "07:30" }
# A reminder that comes due in quiet hours is deferred to the end of the window,
# not dropped. Dropping loses information; firing at 3am trains you to ignore it.
quiet_behaviour = "defer"

[[rules]]
id            = "assignment-lead-times"
subject       = "canvas_assignment"
enabled       = true
lead_times    = ["7d", "3d", "24h", "2h"]
skip_if       = { has_submitted = true }
# Assignments worth less than this get fewer nudges.
[rules.overrides.low_stakes]
when          = { points_possible_lt = 10 }
lead_times    = ["24h"]

[[rules]]
id            = "due-date-moved"
subject       = "canvas_assignment"
enabled       = true
on_event      = "assignment_due_changed"
immediate     = true      # a moved deadline is always worth telling you about now

[[rules]]
id            = "overdue-escalation"
subject       = "canvas_assignment"
enabled       = true
after_due     = ["1h", "24h"]
skip_if       = { has_submitted = true }
stop_after    = 2

[[rules]]
id            = "calendar-events"
subject       = "calendar_event"
enabled       = true
lead_times    = ["1h"]
only_calendars = ["primary"]

[digest]
enabled       = true
at            = "07:30"
# What the morning digest covers.
window        = "48h"
include       = ["due_assignments", "calendar_events", "pending_approvals", "needs_reply_email"]
# Digest prose is the one genuinely contestable part -- what deserves emphasis --
# so this stage does call the model. The FACTS in it are assembled
# deterministically first and passed in; the model orders and phrases, it does
# not decide what is due.
model_role    = "drafting"
skip_if_empty = true
```

### Fire loop

```python
def fire_due_reminders(now: datetime) -> int:
    """Fire reminders whose fire_at has passed.

    SELECT ... FOR UPDATE SKIP LOCKED over reminders_due_idx, then per row:
      - re-check the skip condition against current state (an assignment
        submitted since the reminder was scheduled must not fire)
      - apply quiet hours: defer by updating fire_at, do not drop
      - create a notification row and enqueue push delivery in the SAME
        transaction that sets fired_at

    The last point is I-08's shape applied to notifications: there is no window
    in which a reminder is marked fired but was never announced.
    """
```

### Cross-reference pass

The one part of reminders that warrants a model call. Runs before the digest:

- Deterministic step assembles the facts: what is due in the window, what is on the
  calendar, which flagged emails are unanswered, which approvals are pending.
- If the assembled set is non-trivial (configurable threshold), an agent run is enqueued
  to write the digest prose — noticing that three things are due the same afternoon as a
  five-hour calendar block, for instance.
- The facts are passed in. The model never queries for them, so it cannot miss one.

## Assignment assistance

Owner's decision (N1): both **study** and **draft** modes, configurable.

```toml
# config/agent.toml
[assignments]
enabled = true
# "study" -- explain concepts, retrieve the relevant course material, produce
#            practice problems, review the owner's own work and point at errors.
# "draft" -- additionally produce worked solutions and draft submissions for the
#            owner to review and edit.
mode = "study"

# Per-course override, because different courses have different rules.
[assignments.courses.cse-2431]
mode = "study"

[assignments.output]
# Athena never submits to Canvas, in any mode. This is not configurable.
write_to_vault = true
vault_subdir   = "assignments"
```

### The mode gate

Enforced in code, not in the prompt (same reasoning as I-03):

- The `assignment_context` subagent is available in both modes: it assembles the
  assignment description, the lectures and slides it draws on, and the attached files.
  This is retrieval, and it is the genuinely useful part.
- The `draft` capability is a **separate tool** that is not registered when the effective
  mode for that course is `study`. Not registered-and-refusing — absent. A model cannot
  be talked into calling a tool that does not exist.
- The effective mode is resolved per course, with the course override winning, and is
  recorded on every assignment-related run so the history shows which mode produced what.

### What Athena never does

- Submits anything to Canvas.
- Represents generated work as the owner's own. Every draft written to the vault carries
  `provenance: athena` in frontmatter and a visible header saying so.

The header is not a moral gesture — it is what makes a vault search six weeks later
distinguish the owner's reasoning from the model's, which matters when studying from it.

## Notification routing

```toml
# config/notifications.toml
[channels.web_push]
enabled   = true
vapid_public_key_env  = "ATHENA_VAPID_PUBLIC_KEY"
vapid_private_key_env = "ATHENA_VAPID_PRIVATE_KEY"
vapid_subject         = "mailto:<owner-address>"
ttl_s     = 86400

[categories.approval]
push      = true
throttle  = "none"        # never throttle an approval; it blocks a run

[categories.reminder]
push      = true
throttle  = { max_per_hour = 6, collapse = true }

[categories.digest]
push      = true

[categories.error]
push      = true
throttle  = { max_per_hour = 3, collapse = true }
```

`collapse = true` means N throttled notifications become one summary rather than being
dropped.

**The in-app list is always authoritative** (D-14). Push is a delivery optimization. No
approval, reminder, or error is ever reachable only through a push notification, because
push on iOS is not reliable enough to be a system's only path to its user.
