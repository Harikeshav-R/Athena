# Phase 09 — Web UI

**Objective.** The SPA: chat, vault browser, ingestion upload, notifications, activity,
config viewer. Approvals arrive in Phase 10.

**Preconditions.** Phase 08 gate green.

Read [`12-web-ui.md`](../12-web-ui.md) in full, including the design direction.

---

## Steps

### 1. Scaffold

```bash
npm create vite@latest web -- --template react-ts
cd web && npm i @tanstack/react-query react-router-dom zod
npm i -D vitest @testing-library/react msw @playwright/test eslint typescript
```

`zod` schemas mirroring the API's Pydantic models, so a response shape change is a type
error in the client rather than a runtime surprise. Generate them from
`/api/config/schema` and the OpenAPI document where practical; hand-write where not.

### 2. Design tokens

Implement the palette, type scale, and layout from
[`12-web-ui.md`](../12-web-ui.md#design-direction) as CSS custom properties in one file.

The discipline that carries the design: **`--pending` appears only on things awaiting the
owner.** Not on headings, not on links, not in chat. A lint rule or a review checklist
item enforces this — it is what makes the approval count legible from across a room, and
it stops being true the moment it decorates something else.

### 3. Data layer

TanStack Query for reads. A typed fetch wrapper handling 401 (redirect to login),
correlation ids (surface in error toasts for debuggability), and error normalization.

### 4. SSE client

`web/src/lib/sse.ts`:

- `EventSource` with automatic reconnect.
- Tracks the last `seq` and sends `Last-Event-ID` on reconnect.
- Reconciles replayed events against local state idempotently, so a replay after
  reconnect does not duplicate rendered tokens. This is the part that is subtle; test it
  directly.

### 5. Screens

Chat, Vault, Ingest, Notifications, Activity, Config, per
[`12-web-ui.md`](../12-web-ui.md#screens). Approvals is a placeholder route in this phase.

Chat requirements:

- Streamed tokens rendered progressively.
- Tool calls shown as collapsed disclosures, expandable.
- Citations as inline chips showing the locator (`Lecture 03 · 00:14:22`), linking into
  the vault viewer at the right file. The locator is the useful part; hiding it behind a
  hover defeats the point.

Ingest requirements:

- Drag-and-drop plus a file picker.
- A frontmatter form: course (from enrolled courses), date, title, type. Date and course
  are marked required for lecture and slide types, because unresolvable values fail the
  ingestion later and it is cheaper to ask now.
- Live progress: per-page for PDFs, per-stage for audio.
- Conflict banners with keep-mine / use-Athena's actions.

### 6. PWA shell

`manifest.webmanifest` (`display: "standalone"`, full icon set), a service worker
registered for offline shell caching. Push handling lands in Phase 10; the worker exists
now so installation works.

### 7. Accessibility floor

Responsive to 375px, visible focus rings, WCAG AA contrast on every token pairing, full
keyboard operability, `prefers-reduced-motion` respected.

### 8. Serving

Vite build to `web/dist`, served by `athena-api` as static files with SPA fallback. Same
origin — no CORS in production.

---

## Files produced

```
web/**
src/athena/api/static.py
tests/e2e/**            # Playwright
```

## Tests required

### Vitest

1. SSE client: reconnect sends the correct `Last-Event-ID`.
2. SSE client: replayed events do not duplicate rendered state.
3. Frontmatter form validation: required fields per source type.
4. Zod schemas reject a malformed API response rather than rendering undefined.
5. iOS install detection: standalone false → instructions shown, no permission prompt.

### Playwright

6. Login → chat → ask → streamed answer with citations.
7. Citation chip navigates to the right vault file.
8. Upload a small markdown file → progress → appears in the vault browser.
9. Upload with a frontmatter conflict → banner shown → resolve → persisted.
10. Reload mid-stream → answer completes (replay).
11. Keyboard-only navigation of every primary screen.

## Exit gate

- All tests pass; frontend coverage at the same bar as Python.
- Lighthouse PWA audit passes installability.
- Manual on the actual iPhone over Tailscale: install to Home Screen, log in, ask a
  question, read a cited answer. **The PWA must be installed in this phase**, because
  Phase 10's push depends on it and discovering an installability problem then is worse.
