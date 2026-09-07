# 12 — Web UI

React + TypeScript + Vite SPA, built to static files and served by `athena-api`. Same
origin as the API, so no CORS in production and cookies work without exception.

## API surface

All routes under `/api`, JSON in and out, session cookie auth.

### Auth

```
POST   /api/auth/login          {username, password} → 204 + Set-Cookie
POST   /api/auth/logout         → 204
GET    /api/auth/me             → {id, display_name, timezone}
```

Argon2id password hashing. The session cookie is `HttpOnly`, `Secure`,
`SameSite=Strict`, holding a random token whose SHA-256 is the `sessions` lookup key.
`SameSite=Strict` is safe here because the app is a same-origin SPA with no external
entry points.

Login is rate-limited per username and per source address, with a constant-time
comparison and a fixed minimum response time so a timing difference does not reveal
whether a username exists.

### Threads and chat

```
GET    /api/threads                          → paged
POST   /api/threads                          {kind, title?} → thread
GET    /api/threads/{id}/messages            → paged
POST   /api/threads/{id}/messages            {content} → {run_id}
GET    /api/runs/{id}/events                 → SSE
POST   /api/runs/{id}/cancel                 → 204
```

### Approvals

```
GET    /api/approvals?status=pending         → paged
GET    /api/approvals/{id}                   → full tool_args, run context, summary
POST   /api/approvals/{id}/decide            {decision, args?} → 204
```

`decision` is one of `approve`, `edit`, `reject`; `args` is required for `edit` and is
validated against the tool's argument schema before the run is resumed. An edited
argument set that does not validate is rejected at the API, not discovered by the agent
mid-execution.

### Ingestion

```
POST   /api/ingestions                       multipart: file + declared frontmatter
GET    /api/ingestions?stage=…               → paged, with progress
GET    /api/ingestions/{id}                  → detail incl. conflicts
POST   /api/ingestions/{id}/resolve-conflict {field, resolution}
POST   /api/ingestions/{id}/retry            → 202
```

Uploads are streamed to disk, never buffered in memory — a 90-minute lossless recording
is large. Content type is checked by sniffing magic bytes, not by trusting the declared
type or the extension.

### Vault, search, config, jobs

```
GET    /api/vault/tree?path=…                → directory listing
GET    /api/vault/file?path=…                → rendered markdown + frontmatter
GET    /api/search?q=…&course=…&from=…&to=…  → the same retrieval path the agent uses
GET    /api/config                           → redacted, read-only (D-15: file-only editing)
GET    /api/config/schema                    → JSON Schema, for rendering docs in the UI
GET    /api/jobs?queue=…&status=…            → paged
GET    /api/runs/{id}/trace                  → full run_events for the trace viewer
GET    /api/notifications                    → paged
POST   /api/notifications/{id}/read          → 204
POST   /api/push/subscribe                   {endpoint, keys} → 204
```

`/api/vault/file` resolves through `resolve_within_vault` (I-04). The API is subject to
the same fence as the agent — a path traversal through the file viewer is the same bug as
one through a tool.

`/api/config` is read-only by design (owner's choice J4). It renders the live config with
every `*_env` field showing the variable name and never a value, alongside the JSON Schema
so each setting's documentation is visible in the UI.

## Streaming

SSE, not WebSockets. The stream is one-directional (server → client) and everything the
client sends is a normal request. SSE reconnects automatically, works through every proxy,
and needs no protocol handling.

Replay is what makes it robust:

```
GET /api/runs/{id}/events
Last-Event-ID: 42
```

`run_events.seq` is the event id. A browser that backgrounds on iOS and reconnects
resumes at its last `seq` rather than losing the middle of an answer. The client always
sends `Last-Event-ID` on reconnect.

Frames:

```
event: token         data: {"seq": 43, "text": "..."}
event: tool_call     data: {"seq": 44, "name": "search_vault", "args": {...}}
event: tool_result   data: {"seq": 45, "name": "search_vault", "summary": {...}}
event: interrupt     data: {"seq": 46, "approval_id": "01J..."}
event: done          data: {"seq": 47, "status": "succeeded"}
```

`tool_result` carries a summary, never the full payload — the same reasoning as I-09
applied to the wire.

## Screens

| Screen | Contents |
|---|---|
| **Chat** | Streaming answer, retrieval citations as chips linking into the vault viewer, tool-call disclosure |
| **Approvals** | Pending queue, expiry countdown, full argument diff for `edit`, one-tap approve/reject |
| **Notifications** | Chronological, unread state, deep links |
| **Ingest** | Upload with a frontmatter form, live per-page/per-minute progress, conflict banners |
| **Vault** | Directory tree, rendered markdown, frontmatter panel, "open in Obsidian" link |
| **Config** | Read-only rendering with schema documentation inline |
| **Activity** | Jobs and runs, filterable, with a trace viewer per run |

### Approval screen specifics

This is the screen that determines whether the system is usable, so it gets requirements:

- The **summary line is written by the server**, from `approvals.summary`, not rendered
  from raw arguments. "Send email to `<name>` re: lab extension" is scannable on a lock
  screen; a JSON blob is not.
- Full arguments are one tap away, always, with no truncation.
- Expiry is shown as a countdown, and the consequence is stated: *"Expires in 3h 12m —
  will be rejected."* An owner must never be surprised by a silent expiry.
- `edit` opens a form generated from the tool's argument JSON Schema, so an edited send
  cannot produce arguments the tool will reject.
- Approving requires a deliberate action — no swipe-to-approve, no approve-all button.
  Rejecting can be quick. The asymmetry is the point.

## PWA and push

Requirements, all mandatory for iOS (D-14):

1. `manifest.webmanifest` with `display: "standalone"`, name, and the full icon set.
2. A service worker handling `push` and `notificationclick`.
3. HTTPS. Tailscale's `*.ts.net` certificates are publicly trusted and satisfy the secure
   context requirement.
4. **The PWA must be installed to the iOS Home Screen.** An open Safari tab cannot receive
   push — `PushManager` is not available there. This is Apple's design.
5. The permission prompt must follow a user gesture.

The UI detects `navigator.standalone === false` on iOS and shows the install instructions
inline rather than a permission prompt that would silently do nothing.

```js
// web/src/push/subscribe.ts — the check that must exist
const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
const isStandalone = window.matchMedia("(display-mode: standalone)").matches
  || (window as any).navigator.standalone === true;

// On iOS, PushManager is absent outside standalone mode. Prompting is a no-op
// that leaves the user believing notifications are enabled.
if (isIOS && !isStandalone) {
  showInstallInstructions();
}
```

Subscriptions are per device. A push that returns 404 or 410 marks the subscription dead
and removes it after `failure_count` exceeds the configured limit.

## Design direction

The brief: a private instrument for one person, checked at a glance between classes,
whose most important screen asks *"do you want me to send this?"* It is closer to an
aircraft annunciator panel than to a productivity SaaS app — status must be readable
without reading.

**Palette** — five values, built around a single alert hue that appears nowhere else:

```
--ink        #14161A   text, near-black with a blue cast
--paper      #FBFAF7   background, warm off-white
--rule       #D8D5CD   hairlines, borders
--quiet      #6A6E76   secondary text, metadata
--pending    #B2481F   the alert hue: approvals, expiry, errors. Nothing else.
```

The discipline is the fifth value. `--pending` is reserved for *things awaiting the
owner*. It never decorates a heading, never marks a link, never appears in the chat
transcript. When it is on screen, something needs a decision. That makes the approval
count legible peripherally, which is the whole job of the notification design.

**Type** — one family, a grotesque with a real range of weights, plus a monospace for
timestamps, locators, and code in retrieved slides. Timestamps and vault paths are
data, and setting them in mono makes them scannable and unambiguous — `00:14:22` should
not be kerned like prose.

**Layout** — a single column at reading measure (under 80 characters) for chat and
documents, with a persistent left rail for navigation on desktop that collapses to a
bottom bar on mobile. The approval count lives in the rail, in `--pending`, at all times.

**Structure carries information.** Approval cards get a left border in `--pending`;
resolved ones lose it. Retrieval citations are inline chips with the locator visible
(`Lecture 03 · 00:14:22`), because the locator is the useful part and hiding it behind a
hover defeats the purpose.

**Motion** only on state change: an approval resolving, a card leaving the queue, an
ingestion advancing a page. No entrance animations, no hover transitions on cards.
`prefers-reduced-motion` respected throughout.

Quality floor, non-negotiable: responsive to 375px, visible keyboard focus rings,
WCAG AA contrast on every pairing above, full keyboard operability of the approval queue.

## Frontend testing

- **Vitest** for units: the push capability check, SSE reconnect and replay logic,
  frontmatter form validation, date parsing.
- **Playwright** for flows: login, ask a question and see a streamed answer with
  citations, upload a file and watch progress, receive an interrupt and approve it,
  reject one and confirm the effect did not happen.
- The API is mocked at the network boundary via MSW; Playwright runs against the real
  API with a seeded test database in CI.
- Coverage policy matches the Python side (D-18).
