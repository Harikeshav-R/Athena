# 14 — Deployment

Target: one Mac mini (M4, 16 GB), Docker Desktop for Mac, plus a small number of native
host processes that exist because containers on macOS cannot reach the GPU (D-06).

## Compose topology

```yaml
# docker/compose.yml — structure; see the file itself for the full version
name: athena

services:
  postgres:
    image: postgres:17
    restart: unless-stopped
    environment:
      POSTGRES_DB: athena
      POSTGRES_USER: athena
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./backups:/backups
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U athena -d athena"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks: [internal]

  athena-api:
    build: { context: .., dockerfile: docker/api.Dockerfile }
    restart: unless-stopped
    depends_on:
      postgres: { condition: service_healthy }
    # Published to loopback only. tailscale serve on the host picks this up.
    ports: ["127.0.0.1:8000:8000"]
    volumes:
      - vault:/vault
      - media:/vault/media
      - ../config:/app/config:ro
    environment:
      ATHENA_DATABASE_URL:
      ATHENA_VAULT_ROOT: /vault
      ATHENA_SESSION_SECRET:
      ATHENA_VAPID_PUBLIC_KEY:
      ATHENA_VAPID_PRIVATE_KEY:
    networks: [internal]

  athena-agent-worker:
    build: { context: .., dockerfile: docker/worker.Dockerfile }
    command: ["athena-worker", "--queue", "agent"]
    restart: unless-stopped
    depends_on:
      postgres: { condition: service_healthy }
    volumes:
      - vault:/vault
      - ../config:/app/config:ro
    environment:
      ATHENA_DATABASE_URL:
      ATHENA_VAULT_ROOT: /vault
      ATHENA_OPENROUTER_API_KEY:      # model access only; no mail or Canvas creds
    networks: [internal]

  athena-ingest-worker:
    build: { context: .., dockerfile: docker/worker.Dockerfile }
    command: ["athena-worker", "--queue", "ingest,poll,maintenance"]
    restart: unless-stopped
    extra_hosts:
      - "host.docker.internal:host-gateway"   # reaching the native ASR service
    volumes:
      - vault:/vault
      - media:/vault/media
      - ../config:/app/config:ro
    environment:
      ATHENA_DATABASE_URL:
      ATHENA_VAULT_ROOT: /vault
      ATHENA_OPENROUTER_API_KEY:
    networks: [internal]

  athena-scheduler:
    build: { context: .., dockerfile: docker/worker.Dockerfile }
    command: ["athena-scheduler"]
    restart: unless-stopped
    networks: [internal]

  athena-ml:
    build: { context: .., dockerfile: docker/ml.Dockerfile }
    restart: unless-stopped
    volumes: [models:/models]
    environment:
      ATHENA_ML_DEVICE: cpu          # see note: no GPU inside Docker on macOS
    networks: [internal]

  # Retrieval (D-02). Pinned to an exact released tag -- never :latest, and
  # never a locally built image. Athena must not fork or patch OpenViking:
  # it is AGPLv3, and running the released image unmodified is what keeps
  # Athena's own source obligations unchanged.
  openviking:
    image: volcengine/openviking:<pinned-version>
    restart: unless-stopped
    depends_on:
      athena-ml: { condition: service_healthy }
    volumes:
      - ovdata:/data
      - ../config/openviking.json:/root/.openviking/ov.conf:ro
    environment:
      ATHENA_OPENROUTER_API_KEY:     # VLM for semantic tiering; see D-05 note
    networks: [internal]

  athena-mcp-email:
    build: { context: .., dockerfile: docker/mcp.Dockerfile }
    command: ["athena-mcp", "email"]
    restart: unless-stopped
    environment:
      ATHENA_GMAIL_CLIENT_ID:
      ATHENA_GMAIL_CLIENT_SECRET:
      ATHENA_GMAIL_REFRESH_TOKEN:
      ATHENA_ICLOUD_APP_PASSWORD:
    networks: [internal]

  athena-mcp-calendar:
    build: { context: .., dockerfile: docker/mcp.Dockerfile }
    command: ["athena-mcp", "calendar"]
    restart: unless-stopped
    environment:
      ATHENA_GOOGLE_CLIENT_ID:
      ATHENA_GOOGLE_CLIENT_SECRET:
      ATHENA_GOOGLE_REFRESH_TOKEN:
      ATHENA_ICLOUD_APP_PASSWORD:
    networks: [internal]

  athena-mcp-canvas:
    build: { context: .., dockerfile: docker/mcp.Dockerfile }
    command: ["athena-mcp", "canvas"]
    restart: unless-stopped
    environment:
      ATHENA_CANVAS_BASE_URL:
      ATHENA_CANVAS_TOKEN:
    networks: [internal]

volumes:
  pgdata:
  vault:
  media:
  models:
  ovdata:        # OpenViking's store. Derived and disposable (I-01) -- not backed up.

networks:
  internal:
    driver: bridge
```

Notes on choices visible above:

- **Only `athena-api` publishes a port, and only to `127.0.0.1`.** Nothing binds
  `0.0.0.0`. Tailscale reaches loopback on the host.
- **Config is mounted read-only.** No container can modify its own configuration (I-15).
- **Each service's environment is enumerated.** No service inherits the whole `.env`
  (D-08, [`13-security.md`](13-security.md)).
- **`restart: unless-stopped`** is the supervisor. `launchd` is only responsible for
  bringing the stack up after a reboot, not for individual processes.

## Host services

### Why they exist

Docker Desktop, Podman, and colima all run Linux containers on macOS through a VM built on
`Hypervisor.framework`, which provides no virtual GPU. A container on this machine cannot
reach Metal or the Neural Engine — this is architectural, not configuration. Whisper
large-v3 on VM CPU is roughly an order of magnitude slower than on Metal.

So the ASR service runs natively. Once one service must, making the ML service optionally
native costs nothing and buys real speed.

### `athena-asr`

Installed into its own virtualenv under `~/Library/Application Support/athena/asr`,
managed by `launchd`, bound to `127.0.0.1:8081`.

```xml
<!-- host/launchd/com.athena.asr.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
<dict>
    <key>Label</key><string>com.athena.asr</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/USERNAME/Library/Application Support/athena/asr/.venv/bin/athena-asr</string>
        <string>--host</string><string>127.0.0.1</string>
        <string>--port</string><string>8081</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>/Users/USERNAME/Library/Logs/athena-asr.log</string>
    <key>StandardErrorPath</key><string>/Users/USERNAME/Library/Logs/athena-asr.err.log</string>
</dict>
</plist>
```

Binding to `127.0.0.1` matters: this service has no authentication, and
`host.docker.internal` resolves to the host gateway, which reaches loopback. Binding
`0.0.0.0` would expose transcription to the LAN.

`USERNAME` is templated by `just install-host-services`, not committed as a literal
(I-06).

### Reaching the host from containers

`extra_hosts: ["host.docker.internal:host-gateway"]` on services that need it. Config:

```toml
# config/ingestion.toml — production on macOS
[audio]
base_url = "http://host.docker.internal:8081"

# config/retrieval.toml — production, if using host ML
[embedding]
base_url = "http://host.docker.internal:8082"
```

In CI and on Linux these point at the container services instead. This is the only place
the two deployment modes differ, and it is one config value each.

## Autostart after reboot

Three things must come back, in order:

1. **Docker Desktop.** Enable *Start Docker Desktop when you sign in*, and enable
   automatic login for the Mac mini's user account, because Docker Desktop for Mac needs
   a logged-in GUI session. A headless-style Mac mini that reboots to a login window will
   not start the stack.
2. **The Compose stack.** `restart: unless-stopped` handles it once the daemon is up,
   provided the stack was up when the machine went down. A `launchd` agent additionally
   runs `docker compose up -d` on login as a belt-and-braces measure, waiting on the
   Docker socket first.
3. **Host services.** `launchd` with `RunAtLoad`.

```bash
# host/launchd/athena-stack-up.sh — waits for the Docker socket before composing up
#!/usr/bin/env bash
set -euo pipefail

for _ in $(seq 1 60); do
  if docker info >/dev/null 2>&1; then break; fi
  sleep 5
done
docker info >/dev/null 2>&1 || { echo "docker did not become ready" >&2; exit 1; }

cd "$(dirname "$0")/../../docker"
docker compose up -d
```

The wait loop is not optional. A `launchd` agent firing at login will run before the
Docker daemon is accepting connections, and `docker compose up` will fail with a
confusing socket error.

## Preventing sleep

Containerization does not change this — it is about the physical machine.

```bash
sudo pmset -a sleep 0 disablesleep 1
sudo pmset -a womp 1          # wake for network access
sudo pmset -a autorestart 1   # restart after a power failure
```

Verify with `pmset -g` and `pmset -g assertions`. Display sleep is fine; system sleep is
not, since a sleeping machine misses every poll and delivers no reminders.

## Tailscale

```bash
tailscale up --ssh=false --advertise-tags=tag:athena
tailscale serve --bg --https=443 http://127.0.0.1:8000
```

`tailscale serve` obtains a publicly trusted certificate for the machine's `*.ts.net`
name, which is what makes the PWA a secure context and web push possible (D-14).

Tailscale ACLs restrict `tag:athena` to the owner's devices. Session auth remains the
authorization layer (D-17).

**Do not use `tailscale funnel`.** Funnel exposes the service to the public internet,
which is exactly the thing the polling architecture exists to avoid.

## Resource budget on 16 GB

| Component | Resident, approx | Notes |
|---|---|---|
| Docker Desktop VM | 4 GB allocated | Configure the VM's memory explicitly; the default may be too generous |
| Postgres | 512 MB | `shared_buffers` tuned down from any server default |
| OpenViking | 1–2 GB | Server plus its store. Watch this after the first full index; it is the newest and least predictable line in this table. |
| API + workers + scheduler | 1 GB total | Model weights are not loaded here — this is the payoff of D-06 |
| `athena-ml` (container CPU) | 1.5 GB | Only if not using host mode. Serves OpenViking, not the agent. |
| `athena-asr` (host) | 3–4 GB while transcribing | Peak, not resident; the process idles small |
| `athena-ml` (host) | 1.5 GB | Alternative to the container |
| macOS + headroom | remainder | |

The binding constraint is transcription concurrency. `athena-asr` MUST process one file
at a time by default; two 90-minute lectures in parallel will page.

The second constraint is a **full reindex**, which runs OpenViking's semantic processing
across the whole corpus while embedding every document. Do not run one concurrently with
transcription. `just reindex` refuses if an ASR job is in flight and says why.

## Operational commands

```
just up                      # docker compose up -d --build
just down
just logs [service]
just ps
just migrate                 # alembic upgrade head
just reindex [--from-scratch]
just backup                  # pg_dump + vault tar to ./backups
just doctor                  # health check every dependency and print a report
just install-host-services   # venv + launchd plists for asr/ml
just auth-google             # one-time OAuth flow, prints the refresh token
```

`just doctor` is the first thing to run when something is wrong. It checks: Docker daemon
reachable, every container healthy, Postgres accepting connections and at the expected
migration revision, `athena-ml` and `athena-asr` responding, every configured account's
credentials valid, vault mounted and writable, disk space, sleep assertions, Tailscale
serving, and the count of jobs stuck in `running` with a stale heartbeat.

## Upgrades

1. `just backup`
2. `git pull`
3. Read the release note for `config.example/` changes and apply them to `config/` by
   hand — Athena never rewrites the operator's config (D-15).
4. `just migrate`
5. `just up`
6. `just doctor`

Rollback is `git checkout <previous tag>`, `alembic downgrade`, `just up`. Every
migration having a working `downgrade()` (see
[`06-data-model.md`](06-data-model.md#migrations)) is what makes that sentence true.
