# Phase 10 — Approval queue, interrupts, and push

**Objective.** An interrupt raised in a worker reaches the owner's phone, blocks until
answered, and resolves correctly — including by expiry. No real write tools exist yet;
the toy effect tool from Phase 03 is the subject.

**Preconditions.** Phase 09 gate green, PWA installed on the phone.

**Why before real write tools.** The approval boundary must be proven against a harmless
tool. Debugging the notification path while a real `send_email` exists means debugging it
with live consequences.

---

## Steps

### 1. Dependencies

```bash
uv add pywebpush cryptography
```

### 2. VAPID keys

`just generate-vapid` produces a key pair and prints both, for the owner to place in
`.env`. It prints rather than writing, so no automated process writes a secret to disk
(I-07).

### 3. Push service

`src/athena/notifications/push.py`:

- Send to every active subscription for a user.
- 404/410 marks the subscription dead; remove after `failure_count` exceeds the limit.
- Payload is minimal — title, body, deep link, notification id. **Never the tool
  arguments.** A push payload transits a third-party push service and appears on a lock
  screen; an approval summary is fine, an email body is not.
- Retry with backoff on 5xx.

### 4. Service worker

`web/public/sw.js`:

- `push` handler → `showNotification` with the deep link in `data`.
- `notificationclick` → focus an existing client if one exists, otherwise open the link.
  Focusing rather than always opening avoids stacking windows.
- `pushsubscriptionchange` → re-subscribe and POST the new subscription. Without this,
  push silently stops working when the browser rotates the subscription, and the symptom
  is "notifications used to work."

### 5. Subscription flow

Permission prompt only after a user gesture. On iOS, only when standalone. Subscription
POSTed to `/api/push/subscribe` with a device label.

### 6. Approval queue UI

Per [`12-web-ui.md`](../12-web-ui.md#approval-screen-specifics):

- Server-written summary as the headline; full arguments always one tap away, untruncated.
- Expiry as a countdown **with its consequence stated**: "Expires in 3h 12m — will be
  rejected."
- `edit` opens a form generated from the tool's argument JSON Schema, so an edited call
  cannot produce arguments the tool rejects.
- Approve requires a deliberate action; reject can be quick. The asymmetry is deliberate.
- No approve-all button, in any form.

### 7. Summary generation

`src/athena/approvals/summary.py` — a deterministic, per-tool renderer producing the
one-line summary. Not model-generated: the summary is a security surface, and a
model-written summary that misdescribes the action defeats the approval boundary at the
human layer.

### 8. Expiry sweeper

Scheduled job marking expired approvals and **resuming the run with a `reject`
decision** (D-13), so the agent observes the outcome rather than the run wedging.

### 9. Auto-approval

`src/athena/approvals/rules.py` — match tool name plus argument predicates against
`config/approvals.toml`. Off by default, per action, opt-in only.

Every auto-approved call still writes an `approvals` row (`auto_approved = true`,
`auto_rule = <id>`), an audit entry, and appears in the UI history. Auto-approval changes
who decides, not whether it is recorded.

---

## Files produced

```
src/athena/notifications/{__init__,push,dispatch,throttle}.py
src/athena/approvals/{summary,rules}.py
web/public/sw.js
web/src/push/**
web/src/screens/Approvals/**
tests/integration/notifications/**
tests/acceptance/test_phase_10_approvals.py
```

## Tests required

1. An interrupt creates an approval row and a notification **in one transaction** — no
   state where one exists without the other.
2. Push is attempted for every active subscription.
3. 410 removes the subscription.
4. `pushsubscriptionchange` re-subscribes (Vitest against a mocked SW context).
5. Approve resumes the run and the tool executes.
6. Reject resumes and the tool does not execute — asserted at the effect table.
7. Edit resumes with the edited arguments.
8. Edited arguments failing schema validation are rejected at the API, before resume.
9. Expiry marks `expired`, resumes with reject, and the run reaches a terminal state
   rather than hanging.
10. An auto-approve rule matching → executes without waiting, and still writes the
    approval row, the audit entry, and the rule id.
11. An auto-approve rule **not** matching on arguments → still interrupts. Parametrize
    over near-miss argument sets; this is the test that catches an over-broad matcher.
12. Push payloads contain no tool arguments.
13. A paused run occupies no worker: with `max_concurrent_runs = 1` and one run awaiting
    approval, a second run still starts.

## Exit gate

- All tests pass.
- **Manual, on the phone, with the screen locked:** trigger the toy effect tool. The push
  arrives. Tapping it opens the approval. Approving executes it. The whole loop, on real
  hardware, over Tailscale.
- Manual: trigger an approval, let it expire, confirm the run resolves and the UI shows
  `expired`.
- Manual: put the phone in airplane mode, trigger an approval, restore connectivity. The
  approval is in the queue and clearing it works even though the push was missed — the
  in-app list is authoritative (D-14).
