# Contributing to Athena

Thank you for your interest in contributing to Athena! Athena is a self-hosted, memory-first personal AI agent with strict safety invariants, an unbreakable approval boundary, and a structured 16-phase build sequence.

Before contributing, please read our foundational documentation:
1. [`docs/README.md`](docs/README.md) — Index and reading sequence
2. [`docs/02-invariants.md`](docs/02-invariants.md) — The 15 non-negotiable architectural invariants
3. [`AGENTS.md`](AGENTS.md) — Working rules for humans and coding agents

---

## Development Setup

### Prerequisites
- **Python 3.12+** (managed via [`uv`](https://github.com/astral-sh/uv))
- **Task Runner**: [`just`](https://github.com/casey/just)
- **Docker Desktop** (for containerized dependencies)

### Initial Setup

```bash
# Clone the repository
git clone git@github.com:Harikeshav-R/Athena.git
cd Athena

# Install all Python dependencies & development tools
just install
```

---

## Workflow & Quality Standards

We maintain strict quality, typing, and testing gates. Every pull request must pass the automated gate check.

### Core Commands

| Command | Purpose |
|---|---|
| `just check` | Runs full verification: `lint`, `typecheck`, and `test` |
| `just lint` | Runs `ruff check` and `ruff format --check` |
| `just fmt` | Auto-formats code and organizes imports with `ruff` |
| `just typecheck` | Runs `mypy --strict` |
| `just test` | Runs the test suite with 100% branch coverage enforcement |
| `just test-acceptance`| Runs slow acceptance tests gating phases |
| `just audit` | Runs `pip-audit` for dependency vulnerability scanning |

---

## Branching & Commit Conventions

### Conventional Branches
All work happens on dedicated feature, fix, or phase branches. **Direct pushes to `main` are protected and forbidden.**

- `phase/NN-<slug>` (e.g. `phase/01-configuration`)
- `feat/<feature-name>` (e.g. `feat/retrieval-rrf`)
- `fix/<issue-name>` (e.g. `fix/queue-poll-disconnect`)
- `docs/<doc-name>` (e.g. `docs/adr-0020`)

### Conventional Commits
Commit messages must follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>(<scope>): <short description>
```

**Allowed Scopes**: `config`, `db`, `queue`, `vault`, `ingestion`, `retrieval`, `agent`, `approvals`, `automations`, `api`, `web`, `mcp`, `ml`, `docker`, `docs`, `repo`.

**Examples**:
- `feat(retrieval): add reciprocal rank fusion`
- `fix(queue): poll when the listener is disconnected`
- `chore(repo): scaffold phase 00 repository tooling`

---

## Non-Negotiable Rules

1. **The Vault is the Source of Truth ([I-01](docs/02-invariants.md#i-01))**: OpenViking vector storage is disposable. The markdown vault is the only persistent store of fact.
2. **Every Effect Passes Approval ([I-03](docs/02-invariants.md#i-03))**: Any write action with external consequences must pass an interrupt gate. Never add auto-approval bypasses.
3. **Fenced Filesystem ([I-04](docs/02-invariants.md#i-04))**: Agent filesystem access is strictly bounded to the vault root and ephemeral state.
4. **Secrets in Environment Only ([I-07](docs/02-invariants.md#i-07))**: Never commit secrets, `.env` files, or passwords. Config files reference secrets by environment variable name only.
5. **No Live Accounts in Tests ([I-14](docs/02-invariants.md#i-14))**: Tests are guarded by a socket-level network blocker and must use recorded fixtures and fakes.
6. **100% Branch Coverage**: All code in `src/athena/` must maintain 100% branch coverage with justified pragmas.

---

## Pull Request Checklist

Before submitting a PR:
- [ ] Ensure `just check` passes cleanly.
- [ ] Confirm your branch is rebased on the latest `main`.
- [ ] Fill out the [Pull Request Template](.github/pull_request_template.md) completely.
- [ ] If modifying retrieval, run `just eval-retrieval` and report evaluation deltas.
