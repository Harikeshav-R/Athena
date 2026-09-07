# Phase 15 — Containerize and deploy

**Objective.** The whole stack runs on the Mac mini under Docker Compose, survives a
reboot unattended, and is reachable over Tailscale from the phone.

**Preconditions.** Phase 14 gate green.

Read [`14-deployment.md`](../14-deployment.md) in full first.

---

## Steps

### 1. Dockerfiles

Four, all multi-stage, all non-root, all with healthchecks:

- `api.Dockerfile` — builds the SPA in a Node stage, copies `dist` into the Python image
- `worker.Dockerfile` — shared by agent, ingest, and scheduler; the command differentiates
- `ml.Dockerfile` — **downloads model weights at build time**, not first request, so a
  cold start is not a five-minute stall
- `mcp.Dockerfile` — one image, three commands

Build for `linux/arm64` on the Mac mini. Use `uv` in the builder and copy the resulting
virtualenv, so the runtime image carries no build toolchain.

### 2. Compose

`docker/compose.yml` per [`14-deployment.md`](../14-deployment.md#compose-topology).

The properties that must hold and that a review should check line by line:

- **Only `athena-api` publishes, and only to `127.0.0.1`.** Nothing binds `0.0.0.0`.
- **`config/` is mounted read-only.** No container can modify its own configuration
  (I-15).
- **Each service's environment is enumerated explicitly.** No service inherits the whole
  `.env` (D-08). The agent worker has model access and no mail or Canvas credentials.
- `restart: unless-stopped` everywhere.
- Healthchecks on everything, with `depends_on: condition: service_healthy` where order
  matters.
- Postgres password via Docker secret, not an environment variable.

### 3. Host services

`just install-host-services`: virtualenvs, model weights, templated `launchd` plists with
the real username (I-06), loaded and verified.

### 4. Autostart

- Docker Desktop: *Start when you sign in*, plus automatic login for the machine's user.
  Docker Desktop for Mac needs a logged-in GUI session; a Mac mini that reboots to a
  login window will not start the stack.
- `launchd` agent running `athena-stack-up.sh`, which **waits for the Docker socket**
  before composing up. The wait loop is not optional — a `launchd` agent at login runs
  before the daemon is accepting connections.
- Host services with `RunAtLoad`.

### 5. Sleep prevention

`pmset -a sleep 0 disablesleep 1 womp 1 autorestart 1`. Verify with `pmset -g assertions`.

### 6. Tailscale

`tailscale serve --bg --https=443 http://127.0.0.1:8000`, ACLs restricting `tag:athena` to
the owner's devices.

**Not `tailscale funnel`** — funnel publishes to the internet, which is exactly what the
polling architecture exists to avoid.

### 7. `just doctor`

Checks, each with a clear pass/fail line: Docker reachable; every container healthy;
Postgres up and at the expected migration revision; embedding dimension matches the
schema; `athena-ml` and `athena-asr` responding and reporting their device; every
configured account's credentials valid; vault mounted and writable; free disk space;
`pmset` assertions; Tailscale serving; jobs stuck in `running` with a stale heartbeat;
and **whether `ATHENA_MCP_READ_ONLY` is on**.

### 8. Backup

`just backup` — `pg_dump` plus a vault tarball into `./backups`, with retention from
config. Scheduled nightly.

The index is explicitly **not** backed up (I-01). Recovery is restore-the-markdown and
`just reindex --from-scratch`, which is a much smaller promise than restoring a
consistent vector database.

### 9. Restore rehearsal

Actually do it, on this phase, once: destroy the volumes, restore from backup, reindex,
and confirm the Phase 07 acceptance test still passes. A backup you have not restored is a
hypothesis.

---

## Files produced

```
docker/{compose.yml,api.Dockerfile,worker.Dockerfile,ml.Dockerfile,mcp.Dockerfile,.dockerignore}
host/launchd/{athena-stack-up.sh,com.athena.stack.plist.tmpl}
scripts/{doctor.py,backup.sh,restore.sh}
docs/RUNBOOK.md
```

`docs/RUNBOOK.md` is written in this phase: first-time setup end to end, upgrade
procedure, rollback, restore, and a symptom-to-cause table for the failures seen during
the build.

## Tests required

1. Every image builds for `linux/arm64`.
2. `docker compose up` reaches all-healthy from a cold start.
3. Migrations run before the API accepts traffic.
4. `just doctor` passes on a healthy stack and fails informatively with each dependency
   stopped in turn.
5. Backup produces a restorable artifact; restore into a fresh volume succeeds.
6. **The full acceptance suite passes against the containerized stack**, not just the dev
   environment.
7. No container runs as root.
8. `athena-agent-worker`'s environment contains no mail or Canvas credential — asserted by
   inspecting the running container.
9. Only `athena-api` has a published port, and it is bound to `127.0.0.1`.

## Exit gate

1. `docker compose up -d` from scratch on the Mac mini → all healthy.
2. **`sudo reboot`. Without touching anything, within five minutes: the stack is up, host
   services are up, and the phone can log in and ask a question.**
3. The Phase 07 acceptance test passes against the deployed stack, using real material.
4. An approval raised by the deployed stack reaches the phone and can be cleared.
5. Restore rehearsal completed and documented.
6. `just doctor` green.

Then the final review, which is a task, not a formality:

- Re-read [`13-security.md`](../13-security.md) against the deployed system.
- Re-review every rule in `config/approvals.toml` with all tools present. **A rule set
  that fenced three tools may not fence eight.**
- Confirm every invariant in [`02-invariants.md`](../02-invariants.md) has a test that
  would fail if it were violated. An invariant with no failing test is documentation, not
  an invariant.
