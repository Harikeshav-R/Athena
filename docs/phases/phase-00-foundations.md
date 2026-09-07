# Phase 00 — Repository, tooling, CI

**Objective.** A repository that an agent can work in safely: pinned toolchain, linting,
typing, testing, coverage gate, secret scanning, and CI, all green on a clean clone. No
Athena logic yet.

**Preconditions.** None. This is the first phase.

**Why first.** Every later phase's exit gate is "tests pass." If the test harness is
built after the code, the gates for phases 01–03 are retroactive and nobody actually runs
them.

---

## Steps

### 1. Initialize the repository

```bash
mkdir athena && cd athena
git init
git branch -M main
uv init --package --name athena --python 3.12
```

`--package` produces the `src/` layout. Python 3.12 minimum; do not use 3.13+ syntax
until the floor is raised deliberately.

### 2. `pyproject.toml`

```toml
[project]
name = "athena"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []              # added per phase, never speculatively

[project.scripts]
athena           = "athena.cli:main"
athena-api       = "athena.api.__main__:main"
athena-worker    = "athena.worker.__main__:main"
athena-scheduler = "athena.scheduler.__main__:main"
athena-mcp       = "athena.mcp.__main__:main"

[dependency-groups]
dev = [
  "pytest", "pytest-asyncio", "pytest-cov", "pytest-randomly",
  "testcontainers[postgres]", "hypothesis",
  "ruff", "mypy", "types-python-dateutil",
  "pip-audit",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
line-length = 100
target-version = "py312"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["ALL"]
ignore = [
  "D203", "D213",     # docstring style conflicts with D211/D212
  "COM812",           # conflicts with the formatter
  "FIX", "TD",        # TODO policing; AGENTS.md governs this instead
]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "PLR2004", "ANN"]   # asserts and magic numbers are the point in tests

[tool.ruff.lint.flake8-bandit]
# S110 (try-except-pass) and S112 (try-except-continue) stay enabled: I-12 forbids
# swallowing errors, and these are how it happens in practice.

[tool.mypy]
python_version = "3.12"
strict = true
warn_unreachable = true
disallow_any_explicit = false      # JSONB payloads are genuinely Any at the boundary
plugins = ["pydantic.mypy"]

[[tool.mypy.overrides]]
module = ["tests.*"]
disallow_untyped_defs = false

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
  "acceptance: slow end-to-end tests that gate a phase",
  "integration: requires a real Postgres or ML service",
]
addopts = "-ra --strict-markers --strict-config"

[tool.coverage.run]
branch = true
source = ["src/athena"]
omit = ["src/athena/__main__.py"]

[tool.coverage.report]
fail_under = 100
show_missing = true
exclude_lines = [
  "pragma: no cover",
  "if TYPE_CHECKING:",
  "raise NotImplementedError",
  "@overload",
  "class .*\\(Protocol\\):",
]
```

`select = ["ALL"]` with a small, justified ignore list rather than a curated allowlist:
new rules arrive enabled, and turning one off is a deliberate act with a comment.

### 3. `justfile`

```make
default: check

install:
    uv sync --all-groups
    cd web && npm ci

check: lint typecheck test

lint:
    uv run ruff check .
    uv run ruff format --check .

fmt:
    uv run ruff check --fix .
    uv run ruff format .

typecheck:
    uv run mypy src tests

test:
    uv run pytest -m "not acceptance" --cov --cov-report=term-missing

test-acceptance:
    uv run pytest -m acceptance

secrets:
    uv run gitleaks detect --no-banner --redact

audit:
    uv run pip-audit
```

Later phases extend the `justfile`; they never replace these targets.

### 4. Pre-commit

`.pre-commit-config.yaml` running: `ruff check --fix`, `ruff format`, `gitleaks`,
`check-added-large-files` (the vault and media must never be committed),
`check-merge-conflict`, `end-of-file-fixer`.

### 5. `.gitignore`

Must include, and this list is security-relevant:

```
.env
.env.*
!.env.example
config/                # the live config; config.example/ IS committed
vault/
media/
models/
backups/
*.db
.venv/
node_modules/
.coverage*
htmlcov/
```

### 6. Structured logging

`src/athena/observability/logging.py`:

- JSON output to stdout; containers do not manage log files.
- A `logging.Filter` that redacts the values of every environment variable whose name
  matches the secret patterns, applied to every record (I-07). It is installed by
  `configure_logging()`, which every entrypoint calls before anything else.
- A `correlation_id` `ContextVar` bound per request and per job, so a run's log lines can
  be gathered.

The redaction filter is written in this phase, before there is anything to redact,
because retrofitting it means auditing every existing log call.

### 7. CI

`.github/workflows/ci.yml` with the jobs from
[`15-testing.md`](../15-testing.md#ci). Cache `uv` and `npm`. Fail on any job.

Branch protection on `main`: no direct pushes, all checks required, linear history.

### 8. Documentation and agent rules

Copy `docs/` and `AGENTS.md` into the repository. Commit them before any code, so the
rules exist before the first line an agent writes.

---

## Files produced

```
.github/workflows/ci.yml
.gitignore
.pre-commit-config.yaml
AGENTS.md
docs/**
justfile
pyproject.toml
uv.lock
src/athena/__init__.py
src/athena/observability/logging.py
tests/conftest.py                      # the network guard from 15-testing.md
tests/unit/test_logging_redaction.py
```

## Tests required

1. The redaction filter removes a known secret value from a log record, including when
   the value appears inside a larger string and inside a nested dict.
2. `correlation_id` propagates into records emitted from a task.
3. The network guard raises on a disallowed host and permits an allowed one.

## Exit gate

- `just check` passes on a clean clone with only `just install` run first.
- `just secrets` passes.
- CI is green on `main`.
- Coverage is 100% (trivially, since there is little code — but the gate is armed).
