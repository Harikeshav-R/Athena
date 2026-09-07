# Phase 04 — Vault bootstrap and filesystem fencing

**Objective.** Athena creates and owns a vault, the agent can read and write inside it,
and cannot reach anything outside it. Frontmatter parsing and writing work.

**Preconditions.** Phase 03 gate green.

Read [`05-vault-schema.md`](../05-vault-schema.md) in full first.

---

## Steps

### 1. Dependencies

```bash
uv add python-frontmatter python-slugify
```

### 2. Path fencing

`src/athena/vault/paths.py` — `resolve_within_vault` verbatim from
[`05-vault-schema.md`](../05-vault-schema.md#filesystem-fencing).

The detail that matters: resolution happens **after** symlink resolution. A prefix check
on the unresolved string passes for a symlink inside the vault pointing at `/etc`, which
is the realistic attack, not literal `../..` in a path.

### 3. Bootstrap

`src/athena/vault/bootstrap.py`. Idempotent, non-destructive, returns a report of what it
created. It creates missing directories and missing seed files and **never** modifies or
deletes an existing file — the vault holds the owner's writing, and a bootstrap that
"repairs" it is a data-loss bug.

Runs at API and worker startup, guarded so concurrent starts do not race
(`os.makedirs(exist_ok=True)` plus atomic seed-file creation via `O_EXCL`).

### 4. Frontmatter

`src/athena/vault/frontmatter.py`:

- Typed models per `source_type`, mirroring
  [`05-vault-schema.md`](../05-vault-schema.md#frontmatter-schema).
- Parse with tolerance: an unknown key is preserved on round-trip, not dropped. The owner
  may add their own fields and Athena rewriting the file must not delete them.
- Serialize with stable key ordering, so a rewrite produces a minimal diff in the owner's
  git history if they version the vault.

### 5. Atomic writes

`src/athena/vault/writer.py` — write to `.athena-tmp-<ulid>` in the same directory, fsync,
`os.replace()`. The watcher ignores that prefix.

The writer is also where the secret scan runs (I-07): before writing, scan the content for
the values of known secret environment variables and refuse if found.

### 6. Backend wiring

`make_backend` from [`09-agent.md`](../09-agent.md#backend-wiring), and
`filesystem_permissions` restricting the filesystem tools to `/vault/`.

Both walls, as required by I-04. Add `/retrieved/` to the `StateBackend` namespace
explicitly so nobody later routes it to disk.

### 7. Naming

`src/athena/vault/naming.py` — render paths from the `naming` templates in `vault.toml`,
slugify with a configured max length, and resolve collisions by appending `-2`, `-3`,
never by overwriting.

---

## Files produced

```
src/athena/vault/{__init__,paths,bootstrap,frontmatter,writer,naming}.py
tests/unit/vault/**
tests/acceptance/test_phase_04_fencing.py
```

## Tests required

### Fencing — parametrized, against both the agent tools and the raw resolver

1. `../../../etc/passwd`
2. Absolute paths: `/etc/passwd`, `/app/config/accounts.toml`, `/.env`
3. **A symlink planted inside the vault pointing outside it** — read and write
4. `..%2f..%2f` and other encodings, through whichever layer decodes
5. Null bytes and other path oddities
6. A legitimate deep path inside the vault succeeds (the fence must not be so tight it
   breaks normal use)

### Bootstrap

7. On an empty directory: full skeleton created.
8. Run twice: second run changes nothing (assert mtimes unchanged).
9. With an existing file at a seed path: file untouched, contents identical.
10. Two concurrent bootstraps: no exception, no duplicated or truncated seed file.

### Frontmatter

11. Round-trip preserves unknown keys.
12. Round-trip is byte-stable for an unchanged document (no spurious diffs).
13. Malformed frontmatter produces a specific error naming the file, not a stack trace.
14. Every `source_type`'s model validates its example from the schema doc.

### Writer

15. A crash mid-write (simulated by failing before `replace`) leaves the original intact
    and no partial file visible.
16. Content containing a known secret value is refused.

## Exit gate

- The full fencing matrix passes against both the agent tool path and the resolver.
- Bootstrap is idempotent, proven by mtime comparison.
- 100% coverage on `src/athena/vault`.
- Manual check: open the bootstrapped vault in Obsidian; it opens without warnings and
  the structure is navigable.
