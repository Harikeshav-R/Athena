# Phase 14 — Assignment assistance

**Objective.** Assemble the material an assignment draws on, and help the owner work on
it, with the study/draft mode gate enforced in code.

**Preconditions.** Phase 13 gate green.

---

## Steps

### 1. Assignment notes

The Canvas poller writes an assignment note into
`courses/<slug>/assignments/<assignment-slug>.md`: description converted from HTML to
markdown, due date, points, submission types, and links to attached files as vault paths
where those files have been ingested.

The note is Athena-authored (`provenance: athena`) and regenerated on change, but the
regenerator **preserves any content below a marked boundary**:

```markdown
<!-- athena:managed:end -->

## My notes
```

Everything above the marker is regenerated; everything below is the owner's and is never
touched. Without this, the owner's working notes are destroyed the first time Canvas
updates a description.

### 2. `assignment_context` subagent

Given an assignment, assemble:

- the assignment description
- lectures and slides from the weeks it covers, via `search_vault` with course and date
  filters
- attached files
- related notes

Output is a structured context object with citations. This is retrieval, and it is the
genuinely useful part of the feature — available in **both** modes.

### 3. The mode gate

`src/athena/automations/assignment_mode.py`.

- Effective mode resolves per course, course override winning over the global default.
- In `study`, the drafting tool **is not registered**. Absent, not refusing. A model
  cannot be talked into calling a tool that does not exist. This is the same enforcement
  shape as I-03 and for the same reason.
- The effective mode is recorded on every assignment-related run, so the history shows
  which mode produced what.

### 4. Study mode capabilities

- Explain concepts, grounded in the course's own material rather than general knowledge —
  the value is that it explains it the way the instructor did.
- Generate practice problems from lecture material.
- Review the owner's own work and point at errors, without rewriting it.

### 5. Draft mode capabilities

Everything in study mode, plus worked solutions and draft submissions written to the
vault.

Every generated draft carries `provenance: athena` in frontmatter and a visible header:

```markdown
> Drafted by Athena on 2026-11-02 in draft mode. Review before use.
```

This is not a moral gesture. Six weeks later, a vault search must distinguish the owner's
reasoning from the model's, or studying from your own notes becomes studying from a
model's output without knowing it.

### 6. Never submit

There is no Canvas write tool and no submission path, in any mode. Not configurable.

---

## Files produced

```
src/athena/automations/{assignment_notes,assignment_mode}.py
src/athena/agent/subagents/assignment_context.py
src/athena/agent/tools/draft_solution.py
prompts/{assignment_context,draft_solution}.md
tests/acceptance/test_phase_14_assignments.py
```

## Tests required

1. Assignment note generated with correct fields and vault-path links to ingested files.
2. Regeneration preserves content below `athena:managed:end` — asserted byte for byte.
3. Regeneration updates content above it when Canvas changes.
4. `assignment_context` retrieves material from the right weeks, with citations.
5. **In `study` mode the drafting tool is absent from the tool list.** Parametrized over
   global and per-course settings.
6. A per-course override beats the global default, in both directions.
7. In `draft` mode, generated work carries `provenance: athena` and the visible header.
8. **No Canvas write tool exists in any mode** — asserted against `tools/list`.
9. The effective mode is recorded on the run.

## Exit gate

- All tests pass.
- Manual, on a real assignment in study mode: ask for an explanation of a concept it
  involves. The answer draws on the course's own lectures, with citations, and is more
  useful than a generic explanation would be. If it is not, the value of this feature is
  the retrieval and the retrieval is not working — go back to Phase 07's evaluation set.
- Manual: confirm the mode gate by switching a course to `study` and confirming the
  drafting tool disappears.
