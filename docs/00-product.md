# 00 — Product definition

## What Athena is

Athena is a personal AI agent that runs continuously on hardware its owner controls.
It has three jobs:

1. **Remember.** Ingest the owner's material — lecture recordings, slide decks, typed
   notes, Canvas course files, email, calendar — into a plain-markdown vault, and answer
   questions against it with citations back to the source.
2. **Act.** Send and reply to email, create and modify calendar events, and read Canvas,
   under an explicit human approval gate for anything with an external effect.
3. **Remind.** Cross-reference due dates, calendar, and flagged email into notifications
   delivered to the owner's phone and desktop.

It is a daemon, not a chat session. Most of what it does happens while nobody is
watching; the web UI is where the owner inspects, steers, and approves.

## What Athena is not

- Not a hosted service. Everything runs on one machine the owner owns, reachable only
  over Tailscale.
- Not a general assistant with an open tool surface. The tool set is fixed, enumerated,
  and each write-capable tool is individually gated.
- Not a system that will act without permission. There is no "autonomous mode" toggle
  that removes the approval boundary. Auto-approval exists but only per-action and only
  when explicitly configured (see [`13-security.md`](13-security.md)).

## Deployment context

| Property | Value |
|---|---|
| Host | Mac mini, Apple M4, 16 GB unified memory, kept awake, at home |
| Runtime | Docker Desktop for Mac + a small number of native host processes |
| Access | Tailscale; the UI is a PWA installed to the owner's iPhone home screen |
| Users | One today. The schema and auth model assume more are possible. |
| Model access | OpenRouter free-tier models for all LLM calls in the MVP |
| Repository | Public, single repo, MIT |

## MVP scope

The MVP is exactly the following. Anything not on this list is out of scope, and code
should not be written to accommodate it speculatively.

### 1. Personal brain

- **Ingestion** of: audio recordings (transcribed on the host with word-level
  timestamps), PDF slide decks (rendered per page and converted to markdown by a vision
  model), typed markdown notes, files attached to Canvas assignments and modules, email
  bodies, and calendar events.
- **Storage** in a plain-markdown Obsidian-compatible vault that Athena bootstraps and
  owns, with a defined frontmatter schema.
- **Retrieval** by OpenViking, running locally: path-scoped semantic search where the
  vault's directory tree acts as the filter for course, date, and source type.
- **Interactive query** through the web UI, answered by a synthesis subagent that cites
  vault paths and abstains when retrieval returns nothing.

### 2. Email

- Read the full inbox of every configured account: Gmail (OAuth), iCloud
  (IMAP + app-specific password), and any other IMAP/SMTP provider.
- A deterministic, user-configurable sender-rule pre-filter decides which messages reach
  the model at all.
- Draft replies only to messages the agent judges to need one.
- **Send** — real send, over SMTP or the Gmail API — only after an approval decision.

### 3. Calendar

- Read and write Google Calendar (OAuth) and Apple Calendar (CalDAV + app-specific
  password).
- Create events directly (post-approval) from email content or a direct instruction.

### 4. Canvas LMS

- Read the owner's Ohio State Canvas instance with a personal API token: enrolled
  courses for the current term, assignments, due dates, and files attached to
  assignments and modules.
- Write assignment notes into the vault. Feed the reminder engine.

### 5. Reminders

- Lead-time reminders before due dates, a daily digest at a configured time, quiet hours,
  and escalation for overdue items. All lead times, times, and thresholds configurable.

### 6. Assignment assistance

- Assemble the relevant context for an assignment (its description, the course material
  it draws on, the attached files) and help the owner work on it.
- Two configured modes, `study` and `draft` — see
  [`11-automations.md`](11-automations.md#assignment-assistance) for the exact
  definitions and the gate between them.

### 7. Web UI

Chat, approval queue, notifications, ingestion upload, vault browser, config viewer,
job/run history, agent trace viewer. Login-protected.

## Explicit non-goals

| Non-goal | Why it is excluded |
|---|---|
| Webhooks / public HTTPS ingress | Would expose the home network. Polling is sufficient at this cadence. |
| Local LLM inference (Ollama) | Deferred. Docker on macOS has no GPU access, and the host-native path is extra surface for no MVP benefit. |
| Multi-tenant serving machinery | Single user today. Multi-user readiness is a schema property, not a serving architecture. |
| Speculative automation extensibility | Post-MVP automations are unnamed. Building a plugin system for them now would be guessing. |
| Mobile native app | The PWA covers notification and interaction needs. |
| Automatic submission of coursework | Athena never submits anything to Canvas. |

## Glossary

| Term | Meaning |
|---|---|
| **Vault** | The plain-markdown directory tree Athena owns. The source of truth. |
| **Index** | OpenViking's store, derived from the vault and the source mirrors. Disposable. |
| **Document** | One vault file, tracked in the `documents` table. |
| **Scope** | A `viking://` path prefix that bounds a search before ranking. |
| **Run** | One invocation of the agent graph, identified by a `thread_id`. |
| **Job** | A unit of background work in the Postgres queue: an ingest, a poll, a run. |
| **Approval** | A pending human decision on an interrupted tool call. |
| **Interrupt** | LangGraph's mechanism for pausing a run mid-tool-call and persisting state. |
| **Effect** | Any action with a consequence outside Athena: sending mail, writing a calendar event. |
| **ML service** | The embedding and ASR HTTP endpoints, in-container or host-native. |
| **Source type** | `note`, `lecture_transcript`, `slide_deck`, `canvas_file`, `email`, `calendar_event`. |
