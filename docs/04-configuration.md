# 04 — Configuration

Athena's configurability is a product requirement, not a convenience:
**anything an operator could reasonably want to change lives in `config/`** (I-06).

## Layout and precedence

```
config.example/     committed; complete, documented, working defaults
config/             gitignored; the live configuration
.env                gitignored; secrets only
```

`config/` is created by `just init`, which copies `config.example/` and then never
touches it again. Upgrades that add settings ship a `config.example/` change and a
migration note; they never rewrite the operator's files.

Precedence, lowest to highest:

1. Field defaults declared in the Pydantic model
2. `config.example/<domain>.toml` — **not read at runtime**; it exists only as the source
   for `just init` and as documentation
3. `config/<domain>.toml`
4. Environment variables, prefixed `ATHENA_`, `__` as the nesting delimiter
   (`ATHENA_RETRIEVAL__RERANK__ENABLED=false`)

Environment override exists so a container can be run with one setting changed without
mutating a mounted file. It is not the primary surface.

## Files

| File | Owns |
|---|---|
| `server.toml` | Bind address, workers, session policy, CORS, VAPID, timezone |
| `agent.toml` | Model per role, fallbacks, limits, subagent definitions, prompt paths |
| `retrieval.toml` | OpenViking endpoint, embedding endpoint, scope resolution, offload budgets |
| `ingestion.toml` | Converters, ASR settings, PDF pipeline, upload limits, watchers |
| `accounts.toml` | Email accounts, calendars, Canvas — connection details, never secrets |
| `vault.toml` | Vault root, folder structure, frontmatter schema, naming rules |
| `approvals.toml` | Which tools interrupt, allowed decisions, expiry, auto-approve rules |
| `reminders.toml` | Lead times, digest time, quiet hours, escalation |
| `notifications.toml` | Channels, per-category routing, throttling |
| `schedules.toml` | Poll intervals and cron expressions for every recurring job |

## Schema and validation

Each file maps to one Pydantic Settings model in `src/athena/config/models/`.

<!-- verbatim -->
```python
# src/athena/config/models/base.py
from pydantic import BaseModel, ConfigDict


class AthenaConfigModel(BaseModel):
    """Base for every configuration model.

    extra="forbid" is the point of this class: an unrecognised key is an error,
    not a setting that is silently ignored. A misspelled key in a 500-line config
    surface is otherwise invisible until the behaviour it was meant to change
    fails to change.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
        str_strip_whitespace=True,
    )
```

`frozen=True` matters: a config object is immutable, so hot reload is an atomic pointer
swap rather than mutation observed halfway through by a running job.

### Secret references

Secrets never appear in TOML (I-07). Config names the environment variable:

```toml
[[accounts.email]]
id             = "personal-icloud"
provider       = "imap"
address        = "hari@icloud.com"
imap_host      = "imap.mail.me.com"
imap_port      = 993
smtp_host      = "smtp.mail.me.com"
smtp_port      = 587
password_env   = "ATHENA_ICLOUD_APP_PASSWORD"
```

Enforced by a shared validator:

<!-- verbatim -->
```python
# src/athena/config/validators.py
import os
import re

from pydantic import AfterValidator
from typing import Annotated

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_FORBIDDEN_KEYS = frozenset({"password", "token", "secret", "api_key", "client_secret"})


def _validate_env_reference(value: str) -> str:
    """A *_env field must name an environment variable, not contain a value."""
    if not _ENV_NAME.match(value):
        msg = (
            f"{value!r} is not a valid environment variable name. Fields ending in "
            "_env must reference a variable by name; secrets must never appear in "
            "configuration files."
        )
        raise ValueError(msg)
    if value not in os.environ:
        msg = f"Environment variable {value} is referenced by configuration but is not set."
        raise ValueError(msg)
    return value


EnvVarName = Annotated[str, AfterValidator(_validate_env_reference)]
```

The presence check runs at load, so a missing secret fails at startup with the variable
named, rather than at 3am when a poll fires.

`_FORBIDDEN_KEYS` is checked by a model validator on `AthenaConfigModel` subclasses: a
config key with one of those names is rejected outright regardless of its value.

### Reload classification

Every field declares whether it can be hot-applied.

<!-- verbatim -->
```python
from typing import Annotated
from pydantic import Field

# Field metadata: reloadable=False means a change requires a process restart.
NonReloadable = Field(json_schema_extra={"reloadable": False})
```

On reload, the loader diffs old and new, and for any changed field marked
`reloadable=False` it **keeps the old value in the live object** and logs a warning
naming the field and stating that a restart is required. It MUST NOT partially apply a
restart-only change — half-applied config is worse than unapplied config.

Non-reloadable by definition: bind address and port, database URL, worker counts, vault
root, embedding model identity and dimension (changing it requires a reindex, which is an
explicit command, not a side effect of saving a file).

## Loading and hot reload

<!-- verbatim -->
```python
# src/athena/config/store.py
from __future__ import annotations

import threading
from pathlib import Path

from athena.config.models.root import AthenaConfig


class ConfigStore:
    """Holds the live configuration behind an atomic swap.

    Consumers MUST call get() at use time. Caching a value at import time defeats
    hot reload and produces a system whose behaviour depends on start order.
    """

    def __init__(self, config_dir: Path) -> None:
        self._config_dir = config_dir
        self._lock = threading.Lock()
        self._current: AthenaConfig = AthenaConfig.load(config_dir)

    def get(self) -> AthenaConfig:
        return self._current  # attribute read is atomic; object is frozen

    def reload(self) -> AthenaConfig:
        """Load, validate, diff, and swap. On validation failure the live config
        is left untouched and the error is raised to the caller (which logs it).
        A bad edit must never take the daemon down or leave it half-configured.
        """
        candidate = AthenaConfig.load(self._config_dir)
        with self._lock:
            merged = self._current.merge_non_reloadable(candidate)
            self._current = merged
        return merged
```

The watcher uses `watchfiles` with a debounce (a text editor writes a file several times
in a second), calls `reload()`, and on failure logs the validation error and keeps
serving the previous configuration. **A syntax error in a config file must never stop the
daemon.**

Hot reload is per-process. Every process that reads config runs its own watcher; there is
no reload broadcast, because there is no shared config state to coordinate.

## Worked examples

### `config/agent.toml`

```toml
[models]
# Every role names a model and an ordered fallback list. OpenRouter free-tier
# availability is not guaranteed, so a role with no fallbacks will fail hard.
provider      = "openrouter"
api_key_env   = "ATHENA_OPENROUTER_API_KEY"
base_url      = "https://openrouter.ai/api/v1"

[models.roles.orchestrator]
model         = "<free-tier-model-id>"
fallbacks     = ["<free-tier-model-id-2>"]
temperature   = 0.0
max_tokens    = 4096
timeout_s     = 120

[models.roles.synthesis]
model         = "<free-tier-model-id>"
fallbacks     = ["<free-tier-model-id-2>"]
temperature   = 0.0
max_tokens    = 8192
timeout_s     = 180

[models.roles.triage]
# Runs on every inbound email that survives the sender-rule pre-filter.
# Cheapest acceptable model; the output is a small enum plus a confidence.
model         = "<free-tier-model-id>"
fallbacks     = []
temperature   = 0.0
max_tokens    = 512
timeout_s     = 30

[models.roles.drafting]
model         = "<free-tier-model-id>"
temperature   = 0.3
max_tokens    = 2048

[models.roles.vision]
# Must be image-capable. Used for PDF page → markdown conversion.
model         = "<free-tier-vision-model-id>"
temperature   = 0.0
max_tokens    = 4096

[limits]
max_tool_iterations       = 40
max_run_duration_s        = 900
max_concurrent_runs       = 2
summarization_threshold   = 150_000   # tokens; below deepagents' default, free-tier windows are smaller

[rate_limits]
# Free-tier limits are aggressive. These are per-role token-bucket settings;
# a limited request returns the job to the queue rather than failing the run.
requests_per_minute       = 20
max_retries               = 5
backoff_base_s            = 2.0
backoff_max_s             = 60.0
jitter                    = true

[subagents.synthesis]
enabled       = true
prompt_file   = "prompts/synthesis.md"
model_role    = "synthesis"

[subagents.email_drafter]
enabled       = true
prompt_file   = "prompts/email_drafter.md"
model_role    = "drafting"
```

### `config/retrieval.toml`

```toml
[provider]
# The RetrievalProvider implementation. "openviking" is the only one shipped;
# "pgvector" is the documented fallback (D-19) and is not implemented.
kind        = "openviking"
base_url    = "http://openviking:8000"
timeout_s   = 60

[embedding]
# reloadable = false. OpenViking is configured separately in config/openviking.json;
# these values must match it, and a startup assertion checks that they do. A silent
# mismatch means Athena reports a model it is not using.
base_url    = "http://athena-ml:8082/v1"
model       = "<local-embedding-model-id>"
dimension   = 1024

[scopes]
# The viking:// root each corpus is mounted under. Changing these requires a
# full reindex.
vault_root    = "viking://resources/vault"
email_root    = "viking://resources/email"
calendar_root = "viking://resources/calendar"

# When a date range spans more than this many months, scope to the year rather
# than enumerating months, to keep the scope list bounded.
max_month_scopes = 6

# An unresolvable filter raises. This is NOT a switch to disable that; it
# controls whether a *deliberately* unfiltered query is permitted at all.
allow_unscoped_search = true

[search]
candidates  = 40      # URIs recall may return before selection
final_k     = 8       # URIs actually read and offloaded

[offload]
# I-09: full content never enters the main thread.
directory         = "/retrieved"
preview_chars     = 200
max_result_tokens = 1500

[index]
# Nightly catch-up over documents with indexed_at IS NULL.
catchup_batch_size = 50
submit_timeout_s   = 300
retry_max          = 3
```

### `config/approvals.toml`

```toml
[defaults]
expiry_minutes      = 720          # 12h; expiry resolves to REJECT (D-13)
allowed_decisions   = ["approve", "edit", "reject"]

[tools.send_email]
interrupt           = true
expiry_minutes      = 240
allowed_decisions   = ["approve", "edit", "reject"]

[tools.reply_email]
interrupt           = true
expiry_minutes      = 240

[tools.create_calendar_event]
interrupt           = true
expiry_minutes      = 1440

[tools.update_calendar_event]
interrupt           = true

[tools.delete_calendar_event]
interrupt           = true
allowed_decisions   = ["approve", "reject"]   # no silent edit on a delete

# Auto-approval is per action and opt-in only (I-15, D-13).
# A rule matches on tool name plus argument predicates. Every auto-approved
# call is still recorded in the audit log and shown in the UI.
[[auto_approve]]
tool        = "create_calendar_event"
enabled     = false
description = "Canvas due dates mirrored into the calendar"
[auto_approve.when]
source              = "canvas_due_date"
calendar_id         = "athena-coursework"
```

## Testing the configuration surface

Required tests, enforced in Phase 01:

1. Every file in `config.example/` loads and validates.
2. Every model rejects an unknown key with a message naming the key.
3. Every `*_env` field rejects a literal-looking value.
4. A restart-only change is not applied on reload, and produces a warning naming
   the field.
5. A malformed TOML file leaves the previous config live and does not raise out of
   the watcher.
6. Round-trip: for every field, an environment variable can override it.
