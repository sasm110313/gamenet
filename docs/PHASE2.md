# Phase 2 — Personal Rates, Remote Management and Cloud Deployment

Status: implemented and deployed to the cloud host. The backend suite passes
**119 tests** on PostgreSQL. Windows 7 SP1 / Windows 10 hardware acceptance is
still pending.

Phase 2 deliberately adds only what was requested: named per-customer rates,
real edge↔cloud command round-trips, and a lightweight production deployment.
It does **not** add shifts, reports, buffet/POS, or similar modules.

## 1. Named personal rates

A customer may now have several named hourly rates:

```
CustomerRate
  customer, name, hourly_rate
  is_default, is_active, revision
  unique(edge_id, customer, name)
  partial unique(customer) where is_default AND is_active
```

Rules:

- The first active rate becomes the default automatically.
- Promoting another rate clears the old default in the same transaction.
- Explicitly clearing a default promotes another active rate; active rates never
  end up without one.
- Deactivating the default promotes the oldest remaining active rate.
- A rate that belongs to one customer can never be selected for another.

At session start the edge resolves the rate in this order:

1. the personal rate explicitly selected by the operator,
2. the customer's default personal rate,
3. the customer's group tariff,
4. the global default hourly rate.

The chosen name and hourly rate are **copied into the session row**
(`customer_rate`, `tariff_name`, `hourly_rate`). Editing or deactivating a rate
later never reprices a live or historical session. A database check constraint
ensures a session has at most one rate source (`tariff` or `customer_rate`).

## 2. Revision control

`Customer`, `CustomerGroup`, `Tariff` and `CustomerRate` carry a monotonically
increasing `revision`. Remote catalog commands must send `base_revision`:

- `0` means "create if missing"; if the row already exists the command is a
  no-op success (retry safety).
- Otherwise the edge compares the current revision with the base revision inside
  the transaction. A mismatch fails the command with `stale revision` and writes
  nothing. There is no last-write-wins path for catalog changes.

Local edge forms also send the revision they rendered, so an operator editing a
stale page gets a clear conflict message instead of silently overwriting a
colleague's change.

## 3. Command protocol additions

Remote command types added in Phase 2:

```
catalog.customer.upsert
catalog.customer_rate.upsert
catalog.customer_rate.deactivate
catalog.group.upsert
catalog.tariff.upsert
session.start
session.stop
wallet.deposit
wallet.adjust
```

Properties preserved from Phase 0/1:

- Commands are signed by the cloud with the edge's private command key, expire,
  and are verified against the edge identity.
- `RemoteCommand.request_id`, unique per edge, makes the cloud form idempotent.
  A double-click reuses the original command instead of issuing a second
  financial operation.
- `InboundRemoteCommand.command_id` is the exactly-once guard on the edge.
- `execute_command` runs claim → dispatch → terminal status → `command.result`
  in **one transaction**. A crash before commit leaves the command `RECEIVED` and
  retryable; a terminal replay returns `{"status": "already_handled"}`.
- A stale `EXECUTING` row is only reclaimed after a grace period.
- Wallet commands pass the command UUID as `LedgerEntry.source_command_id`, which
  is unique. Even a duplicate execution cannot append a second ledger row.

The cloud never writes `Wallet.balance`, `GamingSession`, or `LedgerEntry`. It
issues a command; the edge applies it and emits the normal event; the cloud
projection updates.

## 4. Cloud management UI

New cloud pages under `/manage/`:

- `/manage/pricing/` — create and update tariffs and groups per edge, with base
  revision and active flags.
- `/manage/customers/` — create customers and open a management page.
- `/manage/customers/<id>/` — edit customer profile, deposit/adjust wallet with a
  mandatory reason, create/update/deactivate personal rates, start a session
  (optionally with a chosen rate), stop an active session, and inspect recent
  commands for that customer.
- The read-only cloud session list now exposes a stop action for active sessions.

Every form embeds a fresh `request_id`. Commands that target an offline edge stay
valid for one hour, so the edge can execute them when it reconnects.

## 5. New events and projections

| Event | Cloud projection |
| --- | --- |
| `customer_rate.created` | upsert `CustomerRate` replica, clear old default |
| `customer_rate.updated` | upsert replica, revision, active/default flags |
| `session.started` | link `customer_rate`, snapshot name/rate |
| `ledger.entry_created` | carry `source_command_id` into the replica ledger |

Projections remain fail-closed: a rate event for an unknown customer, or a
session that references an unknown or foreign rate, rejects the event and the
edge retries.

## 6. Lightweight production deployment

Target: `gamenet.hammasjedy.ir` (`185.231.115.130`, Tailscale
`100.67.108.33`), Ubuntu 24.04, 1 vCPU, ~1 GiB RAM, alongside the existing
`masjed` (:8000) and `samen` (:8003) apps.

Topology:

```
Internet :443 → Nginx (TLS, static, WebSocket upgrade)
              → uvicorn 127.0.0.1:18443 (one worker)
              → PostgreSQL 16 (local) + Redis 7 (local, WSS fan-out only)
```

Resource guards:

- PostgreSQL tuned small (`shared_buffers=128MB`, `max_connections=30`).
- Redis `maxmemory=48mb`, no persistence, `noeviction`.
- systemd `MemoryHigh=256M`, `MemoryMax=384M`, `CPUQuota=80%`, `Nice=5`.
- Docker daemon is stopped to free RAM because no containers are used.
- The existing Nginx sites are untouched; GameNet uses its own
  `sites-available/gamenet` file and graceful reloads.

Artifacts live in `deploy/`:

```
requirements.prod.txt       pinned runtime deps
install_cloud.sh            idempotent server installer
gamenet-cloud.service       uvicorn unit with memory/CPU guards
nginx-gamenet.conf          isolated server block
postgresql-gamenet.conf     small-host tuning
redis-gamenet.conf          no-persistence WSS layer
backup-gamenet.sh           daily compressed pg_dump
gamenet-backup.service/.timer
env.production.example      production environment template
```

Secrets are generated on the server. The admin password is stored only in
`/root/gamenet-admin.txt` (mode `600`). The database password lives in
`/opt/gamenet/.env` (mode `640`, owner `root:gamenet`).

## 7. Verification

Backend:

```bash
cd backend
.venv/bin/python -m pytest              # 119 passed
GAMENET_ROLE=edge  DJANGO_SETTINGS_MODULE=gamenet.settings.edge  .venv/bin/python manage.py check
GAMENET_ROLE=cloud DJANGO_SETTINGS_MODULE=gamenet.settings.cloud .venv/bin/python manage.py check
```

Phase 2 tests cover:

- one default rate per customer and automatic promotion,
- stale revision rejection,
- snapshot semantics (editing a rate does not reprice a session),
- personal-default → group-tariff fallback,
- duplicate `request_id` and exactly-once wallet posting,
- negative adjustment stopped by the credit limit,
- remote catalog create/update/stale-failure,
- rate and session-rate cloud projection,
- edge rate-management UI and rate-aware session start,
- cloud management UI idempotency.

Live checks after deployment:

```bash
curl -fsS https://gamenet.hammasjedy.ir/healthz
systemctl status gamenet-cloud --no-pager
journalctl -u gamenet-cloud -n 50 --no-pager
systemctl list-timers gamenet-backup.timer
```

Operational checks: admin login, edge registration, WSS command round-trip,
rate sync to cloud, session start/stop from both edge and cloud, wallet deposit,
and ledger projection.

The live run on 2026-11-07 registered a temporary edge, sent 5 seed events, opened
the WSS handshake, then issued `wallet.deposit`, `catalog.customer_rate.upsert`
and `session.start`. All three commands were acknowledged; the cloud replica showed
a 50,000 Toman wallet, a 75,000 Toman default rate at revision 1, and a session
snapshotted at 75,000 Toman. The temporary edge was removed afterwards. Details
are in `docs/evidence/phase2-deploy.md`.

### DNS caveat

`gamenet.hammasjedy.ir` currently resolves to `185.239.1.100`, while the server is
`185.231.115.130`. The site and certificate work when the name is forced to the
server (`curl --resolve`), but public traffic reaches the other host. The A record
must be changed to `185.231.115.130`; otherwise certificate renewal over HTTP-01
will also fail.

## 8. Remaining hardware work

The following still requires real Windows hardware and is not claimed by this
phase:

- Electron 22.3.27 launch on Windows 7 SP1 and Windows 10,
- DPAPI protection of the edge credential file,
- certificate pinning against the production certificate (bundle ISRG Root X1
  via `CLOUD_CA_BUNDLE` if the Windows 7 trust store is stale),
- service restart and x86 installer validation.
