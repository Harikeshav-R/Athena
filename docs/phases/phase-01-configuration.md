# Phase 01 — Configuration system

**Objective.** The full configuration surface: TOML files, Pydantic Settings models,
validation, secret references, hot reload, and env overrides. Nothing else in Athena is
allowed to read a setting any other way.

**Preconditions.** Phase 00 gate green.

**Why now.** I-06 says nothing tunable is hardcoded. If configuration arrives after the
components, every component ships with literals and the retrofit is the whole codebase.
Building it first makes the constraint free.

Read [`04-configuration.md`](../04-configuration.md) in full before starting.

---

## Steps

### 1. Dependencies

```bash
uv add pydantic pydantic-settings watchfiles
```

`tomllib` is stdlib on 3.12. Do not add a TOML library.

### 2. `AthenaConfigModel` base

Exactly as specified in [`04-configuration.md`](../04-configuration.md#schema-and-validation):
`extra="forbid"`, `frozen=True`, `validate_default=True`.

Add a model validator on the base rejecting keys in `_FORBIDDEN_KEYS`
(`password`, `token`, `secret`, `api_key`, `client_secret`), so a secret cannot be added
to any model by any future author without deliberately removing this check.

### 3. `EnvVarName` and the secret-reference validator

As specified. Two behaviours, both tested:

- A value that is not a valid environment variable name is rejected with a message
  explaining that secrets must not appear in config.
- A referenced variable that is not set is rejected **at load**, naming the variable.
  Failing at startup with "ATHENA_CANVAS_TOKEN is referenced but not set" is worth far
  more than a 401 at 3am.

### 4. Per-domain models

One module per file in `src/athena/config/models/`:

```
base.py      server.py    agent.py       retrieval.py   ingestion.py
accounts.py  vault.py     approvals.py   reminders.py   notifications.py
schedules.py root.py
```

`root.py` defines `AthenaConfig`, which composes them and provides:

```python
@classmethod
def load(cls, config_dir: Path) -> "AthenaConfig": ...


def merge_non_reloadable(self, candidate: "AthenaConfig") -> "AthenaConfig": ...


def load_prompt(self, name: str) -> str: ...
```

Write **every** model in this phase, even for components that do not exist yet. A partial
config surface means later phases add settings ad hoc and the shape drifts. The models
are the specification; the components fill in behind them.

### 5. Reload classification

The `reloadable: False` field metadata, and `merge_non_reloadable`, which keeps the old
value for changed non-reloadable fields and returns the list of them for logging.

Non-reloadable, at minimum: `server.bind`, `server.port`, `database.url`, `vault.root`,
`retrieval.embedding.model`, `retrieval.embedding.dimension`, worker counts.

### 6. `ConfigStore` and the watcher

As specified in [`04-configuration.md`](../04-configuration.md#loading-and-hot-reload).

Requirements that are easy to get wrong:

- **Debounce.** Editors write a file several times in a second; without debouncing,
  reload fires repeatedly mid-write and sees truncated TOML.
- **Validation failure must not kill the watcher.** Log the error, keep the previous
  config, keep watching. A syntax error while editing must not take the daemon down.
- **The swap is atomic.** Rebind the attribute; never mutate the live object. `frozen=True`
  makes accidental mutation an error rather than a race.

### 7. Env overrides

`ATHENA_` prefix, `__` nesting delimiter, applied above file values. Verified by a
round-trip test across every field.

### 8. `config.example/`

Write all ten files, complete, with every setting present and commented. This is the
documentation of the configuration surface, so:

- Every setting has a comment explaining what it does and what happens if it changes.
- Values are working defaults, not placeholders, except where a value is necessarily
  personal (account addresses, Canvas URL), which are marked `# REQUIRED`.
- Model IDs are placeholders marked `# REQUIRED`; do not commit a specific free-tier
  model ID, because their availability changes and a stale default fails confusingly.

### 9. `just init`

Copies `config.example/` to `config/` if absent, refuses if present, and prints which
`.env` variables are referenced but unset.

### 10. `.env.example`

Every variable any config file references, with a comment on where to obtain it. No
values.

---

## Files produced

```
src/athena/config/__init__.py         # get_config() -- the only public accessor
src/athena/config/store.py
src/athena/config/validators.py
src/athena/config/watcher.py
src/athena/config/models/*.py
config.example/*.toml
.env.example
prompts/                              # placeholder prompt files
tests/unit/config/**
```

`src/athena/config/__init__.py` exposes `get_config()`. Nothing else imports `ConfigStore`
directly, so there is one place a component can obtain configuration and it always returns
the current value.

## Tests required

1. Every `config.example/*.toml` loads and validates.
2. Unknown key rejected, error names the key and its file.
3. A model with a forbidden key name fails at class definition or load.
4. `*_env` rejects a value-shaped string.
5. `*_env` rejects an unset variable, naming it.
6. Non-reloadable change is not applied; the returned change list names the field.
7. Reloadable change is applied and observable through `get_config()`.
8. Malformed TOML during reload: previous config still live, error logged, watcher alive.
9. Env override for every field (parametrized over the model tree by introspection).
10. `just init` refuses to overwrite an existing `config/`.

## Exit gate

- All of the above pass; coverage 100% on `src/athena/config`.
- `just init` produces a `config/` that loads.
- Editing a reloadable value in a running process changes `get_config()` within the
  debounce window, demonstrated by a test using a real temp directory and a real watcher.
