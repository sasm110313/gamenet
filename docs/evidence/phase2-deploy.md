# Phase 2 cloud deployment evidence

Date: 2026-11-07
Host: `srv4585421623` (`185.231.115.130`, Ubuntu 24.04.5, 1 vCPU, 961 MiB RAM)
Role: cloud (`gamenet-cloud.service`)
Version: `0.2.0-phase2`

## Health

```
$ curl -sS --resolve gamenet.hammasjedy.ir:443:127.0.0.1 \
    https://gamenet.hammasjedy.ir/healthz
{"status": "ok", "role": "cloud", "version": "0.2.0-phase2"}
```

The service runs on `127.0.0.1:18443` behind the isolated Nginx site. Memory
after startup: ~47 MiB (limits: high 256 MiB / max 384 MiB).

## Live end-to-end verification

A temporary edge was registered against the production cloud, then removed
after the checks. No credentials are reproduced here.

```
registered edge_id=01a1b4df-...
first cycle: 5 events sent, 5 accepted, 0 rejected
ws_handshake welcome
commands issued: wallet.deposit, catalog.customer_rate.upsert, session.start
second cycle: 3 commands executed, 8 result/event rows sent, 8 accepted
rid_wallet  wallet.deposit                  ACKNOWLEDGED
rid_rate    catalog.customer_rate.upsert    ACKNOWLEDGED
rid_session session.start                   ACKNOWLEDGED
wallet_balance 50000
rate Live VIP 75000 True 1
session 75000 Live VIP 94f7d75d-...
```

This proves in production:

- edge registration and heartbeats,
- WSS handshake at `/ws/edge/` through Nginx and Redis,
- signed command delivery, exactly-once execution and `command.result`,
- wallet deposit applied by the edge and projected to the cloud,
- personal-rate creation and projection with revision `1`,
- session start with the selected rate snapshotted into the session,
- cleanup of the temporary edge and its replica rows.

## Admin and management UI

```
POST /admin/login/ -> 302
/                    -> 200
/manage/customers/   -> 200
/manage/pricing/     -> 200
/admin/              -> 200
```

The generated admin password is only in `/root/gamenet-admin.txt` (mode `600`).

## Existing workloads

```
masjed  http://127.0.0.1:8000/ -> 200
samen   http://127.0.0.1:8003/ -> 301 (normal redirect)
```

Ports `8000` and `8003` were never touched. The Nginx sites
`masjed-ssl` and `samen.acadeo.ir` remain enabled; the GameNet site is a separate
file and reloads were graceful. Docker (no containers) was stopped and disabled
to free RAM.

## Services and timers

```
gamenet-cloud      active
gamenet-backup.timer active (daily at 04:30 with up to 5 min jitter)
postgresql         active (16.15, localhost only)
redis-server       active (7.0.15, 127.0.0.1:6379, maxmemory 48mb, no persistence)
nginx              active
```

TLS: `/etc/letsencrypt/live/gamenet.hammasjedy.ir/fullchain.pem`, Let's Encrypt,
valid until 2027-02-05. `certbot.timer` is enabled.

A manual run of `gamenet-backup.service` produced
`/var/backups/gamenet/gamenet_cloud-2026-11-07-071944.dump` (215 KiB, root-only)
and `pg_restore --list` parsed 259 TOC entries.

## DNS blocker (action required)

`gamenet.hammasjedy.ir` currently resolves to `185.239.1.100`, which is **not**
this server. The server's public address is `185.231.115.130`.

Consequences:

- `https://gamenet.hammasjedy.ir/healthz` from the public internet reaches the
  other host and returns `404` with a certificate for `hammasjedy.ir`.
- Forcing the name to this server (`curl --resolve ...:443:185.231.115.130`)
  returns `200` with the correct `gamenet.hammasjedy.ir` certificate.
- Certificate renewal uses HTTP-01 and will fail if the A record is not pointed
  at `185.231.115.130` before renewal.

Required DNS change:

```
gamenet.hammasjedy.ir.  A  185.231.115.130
```
