# Athena — documentation index

Athena is a self-hosted, always-on personal AI agent: a memory-first knowledge base
plus action-taking automations, running as a Docker Compose stack on a home Mac mini
and reachable over Tailscale from a browser or phone.

## Reading order

Read in this order the first time. After that, use the table below as a lookup.

| # | Document | What it answers |
|---|---|---|
| 00 | [`00-product.md`](00-product.md) | What Athena is, MVP scope, non-goals, glossary |
| 01 | [`01-architecture.md`](01-architecture.md) | Component topology, control flow, data flow, orchestration split |
| 02 | [`02-invariants.md`](02-invariants.md) | The rules no change may violate |
| 03 | [`03-decisions.md`](03-decisions.md) | Every architectural decision, its rationale, its reversal condition |
| 04 | [`04-configuration.md`](04-configuration.md) | The config system: files, schema, precedence, hot reload |
| 05 | [`05-vault-schema.md`](05-vault-schema.md) | Vault folder layout, frontmatter schema, naming rules |
| 06 | [`06-data-model.md`](06-data-model.md) | Postgres schema (state, mirrors, queue — no vector index) |
| 07 | [`07-ingestion.md`](07-ingestion.md) | Audio → transcript, PDF → markdown, notes, Canvas files, email |
| 08 | [`08-retrieval.md`](08-retrieval.md) | OpenViking, path scoping, the search tool contract, evaluation |
| 09 | [`09-agent.md`](09-agent.md) | Deep Agents wiring, subagents, prompts, model routing |
| 10 | [`10-integrations.md`](10-integrations.md) | The three MCP servers: email, calendar, Canvas |
| 11 | [`11-automations.md`](11-automations.md) | Scheduler, pollers, reminder engine, assignment assistance |
| 12 | [`12-web-ui.md`](12-web-ui.md) | FastAPI backend, SPA, auth, streaming, approval queue, web push |
| 13 | [`13-security.md`](13-security.md) | Permission model, approval boundary, secrets, threat model |
| 14 | [`14-deployment.md`](14-deployment.md) | Compose topology, volumes, host ML services, Tailscale, autostart |
| 15 | [`15-testing.md`](15-testing.md) | Test layering, fixtures, coverage policy, acceptance gates |

## Build sequence

The build is divided into 16 phases. Each phase has its own document under
[`phases/`](phases/) containing objective, preconditions, ordered steps, files
produced, config introduced, tests required, and an exit gate.

**A phase is not complete until its exit gate passes.** Do not begin phase N+1
before phase N's gate is green. See [`AGENTS.md`](../AGENTS.md) at the repository
root for the working rules that govern this.

| Phase | Title | Gate |
|---|---|---|
| [00](phases/phase-00-foundations.md) | Repository, tooling, CI | `just check` green on a clean clone |
| [01](phases/phase-01-configuration.md) | Configuration system | Config loads, validates, hot-reloads |
| [02](phases/phase-02-database.md) | Postgres, schema, migrations | Migrations up/down clean; job queue passes concurrency test |
| [03](phases/phase-03-harness.md) | Deep Agents harness + durability | Kill mid-run, resume same `thread_id`, no duplicate side effects |
| [04](phases/phase-04-vault.md) | Vault bootstrap + filesystem fencing | Agent cannot read or write outside the vault root |
| [05](phases/phase-05-ml-services.md) | Embedding and ASR services | Both respond in container and host mode |
| [06](phases/phase-06-ingestion.md) | Ingestion pipeline | Audio, PDF, markdown, Canvas files land in the vault correctly |
| [07](phases/phase-07-retrieval.md) | OpenViking + scoped retrieval | **ACCEPTANCE GATE** — spikes, then the lecture-recall test |
| [08](phases/phase-08-api.md) | FastAPI backend + auth | Authenticated streaming chat over HTTP |
| [09](phases/phase-09-spa.md) | Web UI | Chat, vault browser, ingestion upload, config viewer |
| [10](phases/phase-10-approvals.md) | Approval queue + interrupts + push | An interrupt reaches the phone and blocks until answered |
| [11](phases/phase-11-mcp-read.md) | MCP servers, read-only | Email, calendar, Canvas readable; no write tool exists yet |
| [12](phases/phase-12-mcp-write.md) | Write paths | Every write interrupts; rejection actually prevents the effect |
| [13](phases/phase-13-automations.md) | Scheduler, pollers, reminders | Reminders fire on schedule against real data |
| [14](phases/phase-14-assignments.md) | Assignment assistance | Assignment context assembled; mode gate enforced |
| [15](phases/phase-15-deployment.md) | Containerize and deploy | Stack survives a Mac mini reboot unattended |

## Conventions used in these documents

- **MUST / MUST NOT / SHOULD** carry their RFC 2119 meanings. A `MUST` is an invariant
  or a direct consequence of one.
- Code blocks are **specifications**. Where a block is meant to be transcribed close to
  verbatim it is preceded by `<!-- verbatim -->`.
- `TODO(verify)` marks a claim that depends on a library version and MUST be checked
  against the installed version before it is relied on.
- File paths are repository-relative unless they begin with `/` in a container context,
  in which case they are container-absolute.
