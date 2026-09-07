# Phase 06 — Ingestion pipeline

**Objective.** Audio, PDFs, markdown, and Canvas files become correctly-framed vault
documents. Frontmatter resolution works, conflicts are recorded, and every conversion is
resumable.

**Preconditions.** Phase 05 gate green.

Read [`07-ingestion.md`](../07-ingestion.md) in full first.

---

## Steps

### 1. Dependencies

```bash
uv add pymupdf pillow python-magic
```

PyMuPDF for rasterization. `python-magic` for content sniffing — the declared MIME type
and the extension are both attacker-controlled and both routinely wrong.

### 2. Ingestion state machine

`src/athena/ingestion/pipeline.py`. Stages: `received → converting → converted →
indexing → done`, with `failed` reachable from any stage.

Every transition is a committed row update. A worker restart mid-conversion resumes from
the recorded stage rather than starting over.

### 3. Converter protocol

```python
class Converter(Protocol):
    source_types: frozenset[str]

    def accepts(self, mime_type: str) -> bool: ...

    async def convert(self, ctx: ConversionContext) -> AsyncIterator[ConversionProgress]: ...
```

Converters yield progress rather than returning once, so a 60-page deck reports per page
and its progress is checkpointed as it goes.

### 4. Audio converter

Calls `athena-asr`, then renders markdown per
[`05-vault-schema.md`](../05-vault-schema.md#lecture-transcripts).

Section-boundary detection is **deterministic first** (I-11): a silence gap longer than
`section_gap_s`, or a speaker change following a long instructor run. The model-based
option exists in config and is off by default — "where does a topic start" does not need
an LLM most of the time, and on a free tier the calls are not free.

Speaker mapping from `_course.md`. The default "most airtime is the instructor" is a
configurable heuristic, and it is labelled as an inference in `frontmatter_inferred`.

### 5. PDF converter

Rasterize at `dpi` → per-page vision call → assemble.

Requirements:

- **Per-page checkpointing** in `ingestions.progress`, written after each page. On
  free-tier models this is what makes a 60-page deck finish at all.
- Page concurrency from config, low by default (rate limits).
- Per-page retry, then a `## Slide N — conversion failed` marker with the page image path.
  A visible gap, not a silent one (I-12).
- The prompt lives in `prompts/pdf_page.md` (I-06), with the requirements from
  [`07-ingestion.md`](../07-ingestion.md#pdf--markdown).

### 6. Markdown converter

Pass-through with frontmatter normalization. Handles the owner's own typed notes, both
uploaded and detected by the vault watcher.

### 7. Frontmatter resolution

`src/athena/ingestion/frontmatter_resolver.py`, implementing the resolution order from
[`07-ingestion.md`](../07-ingestion.md#frontmatter-resolution).

**`date` and `course` never silently default.** Unresolvable means `stage=failed` with a
specific message and a UI prompt. A wrongly-dated lecture is invisible to the query that
needs it and produces no error anywhere — this is the single most likely cause of the
Phase 07 gate failing in the field rather than in the test suite.

### 8. Conflict recording

Declared value wins; the disagreement is written to `ingestion_conflicts` and
`_athena/logs/conflicts.md` and surfaced in the UI (owner's decision, K5).

### 9. Canvas file ingestion

Poller lists files attached to assignments and modules only (K6), downloads changed ones,
routes by sniffed content type, populates frontmatter from Canvas metadata.

### 10. Vault watcher

`watchfiles` over the vault root, ignoring `media/`, `_athena/logs/`, and
`.athena-tmp-*`. A change enqueues an index job. This is how the owner's own edits in
Obsidian get indexed.

### 11. Document structure

Athena does not chunk — OpenViking does (D-02). What Athena controls is the **structure of
the markdown it emits**, which is the only lever on chunk quality. See
[`07-ingestion.md`](../07-ingestion.md#what-athena-still-controls-about-chunking).

Concretely, the converters must emit: `## [HH:MM:SS]` section headings in transcripts,
`## Slide N — <title>` per page in decks, and the source document's own heading tree
preserved everywhere else.

### 12. Path layout

**Dated documents go in `YYYY/MM/` subdirectories**, per the `[naming]` templates in
`vault.toml`. This is not filing tidiness: OpenViking scopes retrieval by path prefix, so
the tree is the filter index (D-03). A flattened path breaks date-scoped retrieval
silently — queries still return results, just from the wrong weeks.

The indexer itself (submission to OpenViking) is built in Phase 07, where it can be tested
against the real service. This phase produces correctly structured, correctly located
vault files and leaves `documents.indexed_at` NULL.

---

## Files produced

```
src/athena/ingestion/{__init__,pipeline,frontmatter_resolver,indexer,watcher}.py
src/athena/ingestion/converters/{__init__,base,audio,pdf,markdown,canvas_file,email}.py
src/athena/ingestion/chunking/{__init__,heading,per_page,time_window,whole}.py
prompts/pdf_page.md
tests/unit/ingestion/**
tests/integration/ingestion/**
```

## Tests required

### Structure and paths

1. Transcript output carries `## [HH:MM:SS]` section headings at detected boundaries.
2. Deck output carries one `## Slide N — <title>` per converted page.
3. Source heading trees are preserved verbatim for markdown and Canvas files.
4. **A dated document is written to `.../YYYY/MM/`**, parametrized over source types and
   across a year boundary.
5. Vault path ↔ viking URI round-trips (the mapping function, tested here even though
   submission is Phase 07).

### Change detection

6. `content_hash` changes when the body changes and not when only mtime changes.
7. A written document has `indexed_at` NULL and appears in the stale set.

### Frontmatter resolution

11. Each field resolves through each source in the documented order.
12. Unresolvable `date` fails the ingestion with a specific message; **it does not default
    to today** — asserted explicitly.
13. Declared/inferred conflict: declared wins, conflict row written, both values recorded.
14. `frontmatter_inferred` lists exactly the fields Athena derived.

### Converters

15. PDF: a 3-page fixture produces the expected markdown structure.
16. PDF: a failure at page 2 with retries exhausted produces the failure marker and the
    other pages convert.
17. PDF: resume from `progress` after a simulated crash re-converts only the remaining
    pages.
18. Audio: the ASR fixture produces markdown with the documented heading and speaker
    format.
19. Content sniffing: a `.pdf` extension on a PNG is routed by content, not extension.

### Watcher

20. Writing a file in the vault enqueues an index job.
21. `.athena-tmp-*` files do not.

## Exit gate

- All the above pass.
- Manual, on the real machine: record 10 minutes of audio, upload it, and confirm the
  vault file is correct — right course, right date, sensible section headings, plausible
  speaker labels, timestamps that line up when you scrub the original audio.
- Manual: ingest a real slide deck from a current course and read the output. It should be
  usable as study material. If it is not, the vision prompt needs work and that work
  belongs in this phase.
