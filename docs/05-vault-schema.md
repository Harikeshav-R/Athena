# 05 — Vault schema

The vault is a plain-markdown directory tree that Athena creates and owns. It is the
source of truth (I-01). It must be readable and editable in Obsidian, but Athena depends
on no Obsidian plugin — no Dataview, no Templater, no Bases. Every convention here is
enforced by Athena's own code.

## Design constraints

1. **A human must be able to navigate it without Athena.** Folder names and file names
   carry meaning; nothing is a UUID.
2. **Every file is self-describing.** Frontmatter alone is enough to index a file
   correctly; the folder is a convenience, not the schema.
3. **Athena's own working files are separated from content.** They live under `_athena/`
   so a directory listing of the vault looks like notes, not machine state.
4. **Coursework is one section, not the structure.** The MVP populates `courses/`, but
   the vault is a general second brain and the top level reflects that.

## Layout

```
vault/
├── _athena/                     # Athena's working area; not content
│   ├── memories/                # curated durable facts (agent-written, human-readable)
│   │   ├── preferences.md
│   │   ├── people.md
│   │   └── projects.md
│   ├── inbox/                   # uploads awaiting classification
│   └── logs/                    # ingestion reports, conflict records
├── courses/
│   └── <course-slug>/           # e.g. cse-2431
│       ├── _course.md           # course metadata; one per course
│       ├── lectures/
│       │   └── 2026/09/2026-09-08-lecture-03.md
│       ├── slides/
│       │   └── 2026/09/2026-09-08-cache-hierarchy.md
│       ├── assignments/
│       │   └── lab-02-scheduling.md
│       ├── readings/
│       └── notes/               # the owner's own typed notes
├── projects/
│   └── <project-slug>/
├── people/
├── journal/
│   └── 2026/09/2026-09-08.md
├── references/                  # standalone documents not tied to a course
└── media/                       # originals; never edited (I-02)
    ├── audio/
    │   └── 2026-09-08-cse2431-lecture03.m4a
    └── pdf/
        └── 2026-09-08-cache-hierarchy.pdf
```

`media/` sits inside the vault so a citation resolves without leaving the tree, but is
excluded from chunking by `vault.toml`. It is on its own Docker volume in production
because it grows quickly and has a different backup profile from the markdown.

Everything above is **configured, not hardcoded** (I-06):

```toml
# config/vault.toml
root = "${ATHENA_VAULT_ROOT}"

[structure]
athena_dir     = "_athena"
memories_dir   = "_athena/memories"
inbox_dir      = "_athena/inbox"
media_dir      = "media"
courses_dir    = "courses"
projects_dir   = "projects"
journal_dir    = "journal"
people_dir     = "people"
references_dir = "references"

[structure.course_subdirs]
lectures    = "lectures"
slides      = "slides"
assignments = "assignments"
readings    = "readings"
notes       = "notes"

[indexing]
# Directories excluded from chunking and embedding.
exclude = ["media", "_athena/logs", "_athena/inbox"]

[naming]
# Rendered with the document's frontmatter fields.
#
# The YYYY/MM/ nesting on dated types is REQUIRED, not cosmetic. OpenViking
# scopes retrieval by path prefix, so this is what makes a date range
# expressible as a set of scopes (D-02, D-03). Flattening these paths breaks
# date-filtered retrieval, and it breaks it silently -- queries still return
# results, just from the wrong weeks.
lecture    = "{year}/{month:02d}/{date}-lecture-{sequence:02d}"
slide_deck = "{year}/{month:02d}/{date}-{title_slug}"
assignment = "{assignment_slug}"
journal    = "{year}/{month:02d}/{date}"
slug_max_length = 60
```

## Frontmatter schema

Every indexable file MUST carry YAML frontmatter. Athena writes it on ingestion; the
owner may write or correct it.

### Common fields — required on every file

| Field | Type | Notes |
|---|---|---|
| `id` | ULID string | Stable across renames. Athena generates it; never edit it. |
| `title` | string | Human title. |
| `source_type` | enum | `note`, `lecture_transcript`, `slide_deck`, `canvas_file`, `reference`, `journal`, `memory` |
| `created` | date-time | UTC (I-13). |
| `updated` | date-time | UTC. |
| `provenance` | enum | `user`, `athena`, `mixed` — who authored the body. |

### Common fields — optional

| Field | Type | Notes |
|---|---|---|
| `date` | date | The date the content is *about*, not when the file was made. The lecture's date. **This is the field date-range filters use.** |
| `course` | string | Course slug. |
| `tags` | list[string] | Free-form. |
| `source_media` | path | Relative to vault root. Required when the body is a lossy conversion (I-02). |
| `source_url` | string | Canvas file URL, etc. |
| `frontmatter_inferred` | list[string] | Field names Athena inferred rather than received. |

### Per-type extensions

```yaml
# lecture_transcript
course: cse-2431
date: 2026-09-08
sequence: 3
instructor: "<name>"
duration_seconds: 4920
source_media: media/audio/2026-09-08-cse2431-lecture03.m4a
asr:
  model: "<asr-model-id>"
  language: en
  diarized: true
  speakers: ["SPEAKER_00", "SPEAKER_01"]
  word_timestamps: true
```

```yaml
# slide_deck
course: cse-2431
date: 2026-09-08
page_count: 42
source_media: media/pdf/2026-09-08-cache-hierarchy.pdf
conversion:
  method: vision
  model: "<vision-model-id>"
  pages_converted: 42
  pages_failed: []
```

```yaml
# canvas_file
course: cse-2431
canvas:
  course_id: 123456
  file_id: 789012
  module: "Week 3"
  assignment_id: 345678
  updated_at: 2026-09-06T14:22:00Z
```

### The `date` field is load-bearing

It determines both the frontmatter and **the path** (see `[naming]` above), and the path
is the retrieval filter. A wrongly-dated lecture is filed in the wrong scope and is
invisible to the query that needs it.

`date` means *the date the content concerns*. For a lecture it is the day it was
delivered, not the day the recording was uploaded. Every date-range filter reads this
field. Getting it wrong is the single most likely cause of the acceptance test failing,
so:

- Ingestion derives it, in order: explicit user input on the upload form → Canvas
  metadata → filename pattern → audio file creation timestamp → **fail and ask**.
- It never silently falls back to "today."

## Body conventions

### Lecture transcripts

Timestamps are what make a lecture navigable, so they are in the body, not only in
metadata. Diarized speaker labels are mapped to names when the owner has configured them.

```markdown
---
id: 01JBQ...
title: "CSE 2431 — Lecture 03: Cache Hierarchy"
source_type: lecture_transcript
course: cse-2431
date: 2026-09-08
sequence: 3
created: 2026-09-08T19:04:11Z
updated: 2026-09-08T19:04:11Z
provenance: athena
source_media: media/audio/2026-09-08-cse2431-lecture03.m4a
---

# CSE 2431 — Lecture 03: Cache Hierarchy

> Transcript generated by Athena. Original audio: [[media/audio/2026-09-08-cse2431-lecture03.m4a]]

## [00:00:00] Opening

**Instructor** [00:00:04] All right, so last time we finished up with virtual memory...

## [00:14:22] Cache levels

**Instructor** [00:14:25] So when we talk about RAM here, the thing to keep straight is...
```

The `## [HH:MM:SS]` headings are section markers emitted at topic boundaries, which the
heading-aware chunker uses. Per-utterance timestamps in the body let a citation resolve
to a moment.

### Slide decks

One `##` heading per slide, numbered, so the per-page chunker has a clean boundary and a
citation can name a slide.

```markdown
## Slide 12 — Direct-Mapped Cache

Each memory address maps to exactly one cache line.

```
index = (address / block_size) % num_lines
```

> **Figure.** A diagram showing a 32-bit address split into tag, index, and offset
> fields, with arrows into a cache array of 64 lines.
```

Figures are described in a blockquote prefixed `**Figure.**` so that (a) the description
is retrievable text and (b) it is visibly not the instructor's words.

### Curated memories

`_athena/memories/*.md` hold durable facts the agent has learned. Short, flat, one fact
per line, each with a date and a source. This is the only place the agent writes its own
conclusions rather than source text.

```markdown
---
id: 01JBR...
title: Preferences
source_type: memory
created: 2026-09-06T00:00:00Z
updated: 2026-09-12T10:31:00Z
provenance: athena
---

- 2026-09-12 — Prefers reminders as a single morning digest rather than per-item pushes. (source: chat, thread 01JBS...)
- 2026-09-10 — Office hours for CSE 2431 are Thursdays 14:00–16:00. (source: courses/cse-2431/_course.md)
```

## Bootstrap

Vault creation is idempotent and runs on startup. It MUST NOT overwrite anything.

<!-- verbatim -->
```python
# src/athena/vault/bootstrap.py
from pathlib import Path

from athena.config.models.vault import VaultConfig


def bootstrap_vault(config: VaultConfig) -> BootstrapReport:
    """Create the vault skeleton if absent. Idempotent and non-destructive.

    Creates missing directories and missing seed files. Never modifies or deletes
    an existing file: the vault may contain the owner's own writing, and a
    bootstrap that "repairs" it is a data-loss bug.
    """
```

Seed files created once:

- `_athena/memories/{preferences,people,projects}.md` — empty, with frontmatter
- `README.md` at the vault root, explaining the layout to a human who opens it in
  Obsidian
- `.gitignore` — the vault is not a git repository by default, but if the owner makes it
  one, `media/` should not be committed
- `.obsidian/` is **not** created. Athena does not manage Obsidian settings.

## Conflict handling

When the owner supplies frontmatter on upload and Athena infers something different, the
conflict is surfaced, never silently resolved (owner's decision, K5).

1. Athena writes the file with **the owner's values**.
2. It records the disagreement in `_athena/logs/conflicts.md` and in the
   `ingestion_conflicts` table.
3. The UI shows a banner on the document and in the ingestion history: *"You set course
   to `cse-2431`; Athena inferred `cse-2421` from the audio. Keep yours / use Athena's."*
4. Fields Athena inferred without contradiction are listed in `frontmatter_inferred` so
   the owner can see what was guessed.

The owner's value wins by default because a wrong `course` or `date` is invisible until a
query silently misses (see "The `date` field is load-bearing"), and the person who
uploaded the file has better information than the inference.

## Filesystem fencing

Every path the agent supplies is resolved and checked before I/O:

<!-- verbatim -->
```python
# src/athena/vault/paths.py
from pathlib import Path


class PathOutsideVaultError(Exception):
    """Raised when a resolved path escapes the vault root."""


def resolve_within_vault(root: Path, candidate: str | Path) -> Path:
    """Resolve `candidate` against `root`, following symlinks, and reject escapes.

    resolve(strict=False) is used so that a not-yet-created file can be validated
    before it is written. The check is on the resolved path, because a symlink
    inside the vault pointing outside it is exactly the case a naive prefix check
    on the unresolved string would miss.
    """
    root_resolved = root.resolve()
    target = (root_resolved / Path(candidate)).resolve()
    if not target.is_relative_to(root_resolved):
        raise PathOutsideVaultError(str(candidate))
    return target
```

This is the second wall behind `deepagents`' `permissions` (I-04, D-01). It exists
because `permissions` is applied by `FilesystemMiddleware` at the tool level and does not
cover direct backend use.
