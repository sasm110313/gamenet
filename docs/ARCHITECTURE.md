# Architecture

Status: Phase 0 (connectivity proof) — decisions here are load-bearing for Phases 1–6.

## 1. Components and trust boundaries

```
 Windows 7 SP1 clients (N)                Windows 10 management PC                     Linux VPS
┌────────────────────────┐   LAN/TLS   ┌──────────────────────────────┐  WSS/HTTPS  ┌──────────────────┐
│ Electron 22.3.27       │────────────▶│ Local Control Hub (Django)   │────────────▶│ Cloud (Django)   │
│ React UI (sandboxed)   │◀────────────│  REST + Channels/WS          │◀────────────│  REST + Channels │
│ main process: launcher │             │  PostgreSQL 18 (authority)   │             │  PostgreSQL 18   │
│ DPAPI token storage    │             │  outbox worker, sync client  │             │  Redis (fan-out) │
└────────────────────────┘             └──────────────────────────────┘             └──────────────────┘
        untrusted-ish device                 site authority                          replica + remote control
```

Three credentials, all unique, all revocable, all hashed at rest:

| Principal | Issued by | Transport | Storage |
|---|---|---|---|
| Client device | Edge, via one-time registration code | `Authorization: Device <id>.<token>` + WS `hello` | Electron `safeStorage` (DPAPI) |
| Edge node | Cloud, via one-time Edge registration code | `Authorization: Edge <uuid>.<secret>` + WS `hello` | `secure_store` (DPAPI on Windows, 0600 file elsewhere) |
| Administrator | Django auth | session cookie + CSRF | browser |

Neither the cloud nor the internet can open a connection into the site. The edge
dials out. Client devices only ever talk to the edge.

## 2. One codebase, two roles

The Local Hub must enforce the same business rules as the cloud and speak the same
contracts, so it is the *same* Django project with `GAMENET_ROLE=cloud|edge`:

- `gamenet/settings/{base,cloud,edge,test}.py` — role settings.
- `gamenet/urls_{cloud,edge}.py` — role URL wiring.
- `apps/*` — business modules, UI-free services.
- `apps/ingress` — cloud-only transport: edge registration, event ingest, command issue, `/ws/edge/`.
- `apps/devices` — edge-only transport: device registration, heartbeat, `/ws/device/`.
- `apps/synchronization` — outbox, inbound command ledger, sync state, both roles.

This avoids the classic failure mode of divergent edge/cloud business logic. The
cost is that role-specific code must be *explicitly* guarded; `check` runs a role
audit at startup (`apps/core/checks.py`).

## 3. Authority and replication

- **Edge is authoritative** for sessions, ledger entries, wallet balances and
  device state. Those writes happen only on the edge.
- **Cloud is a replica** for those aggregates. Ingest projects events into
  read models; it never recomputes a charge or overwrites an edge fact.
- **Cloud is authoritative** for: remote commands, configuration snapshots,
  edge registration, and global reporting.
- There is no last-write-wins on financial data. Conflicts are impossible by
  construction: one writer per aggregate, monotonic sequence per edge.

Every edge fact is an event with a stable `event_id` (UUIDv7-ish, time-sortable)
and a per-edge monotonic `local_sequence` allocated in the same transaction that
writes the business row.

## 4. Edge → Cloud sync (Transactional Outbox)

```
BEGIN
  business write (e.g. ledger entry)
  INSERT outbox_event(event_id, edge_id, local_sequence, type, payload)  -- same tx
COMMIT
```

Drain loop (`sync_outbox` worker):

1. Claim a batch of PENDING events ordered by `local_sequence`.
2. `POST /api/v1/edge/events:batch` with `{"events": [...]}`.
3. Cloud validates edge credential, per-event schema version, `event_id`
   uniqueness `(edge_id, event_id)` and sequence monotonicity.
4. Cloud returns `{"accepted": [...], "duplicates": [...], "watermark": N}`.
   Duplicates are *success* (already applied) — never an error, never re-applied.
5. Edge marks events `SYNCED` + `cloud_acknowledged_at` only for acked ids.
6. Pending/failed counts surface on both dashboards.

Failure handling:

- Network/5xx → exponential backoff with jitter (1s → 60s cap), events stay PENDING.
- 4xx validation → event marked FAILED (poison), excluded from auto-drain, shown
  with a manual retry action. Nothing is ever deleted before acknowledgement.
- Ordering: a batch is sent in sequence order; the cloud rejects a batch whose
  first sequence is beyond `last_sequence + 1` gap for order-sensitive types.
  (Phase 0 enforces per-aggregate ordering; global gap handling is Phase 1.)
- The edge records `last_acked_sequence` locally so restarts resume correctly.

## 5. Cloud → Edge (commands and configuration)

Cloud issues a `RemoteCommand` with `command_id`, `edge_id`, `type`, `payload`,
`issued_at`, `expires_at`, `nonce`, and `signature = HMAC-SHA256(edge_secret,
canonical_json(envelope))`.

Delivery is at-least-once; execution is exactly-once:

- Edge verifies signature, expiry, edge id, and `nonce` uniqueness (DB unique
  constraint on `inbound_commands.command_id`), inside one transaction that also
  records the result.
- Replayed or expired commands are acknowledged as `rejected` with a reason, never
  executed.
- Result is reported back as a `command.result` sync event, which flips the cloud
  command to `acknowledged`.
- Delivery path: WSS push when connected, else `GET /api/v1/edge/commands/pending`
  on the next poll/reconnect. Same payload, same verification.

Configuration is distributed as **versioned snapshots** (`config_version`,
`payload_hash`) rather than field-level patches, so an edge can always prove which
configuration it is running. The edge applies a snapshot atomically and reports
the applied version.

## 6. Offline behaviour

| Failure | Behaviour |
|---|---|
| Internet down | Edge keeps serving LAN; outbox grows in PostgreSQL; dashboards show "cloud offline" + pending count. |
| Cloud restart | Edge reconnects with backoff; WSS re-handshake; missed commands are pulled by id. |
| Edge restart | Outbox and active sessions are in PostgreSQL; sessions are recovered from persisted rows, not memory. |
| Edge DB down | Fail closed: no new sessions, clients stay locked, no untracked money. |
| Client network drop | Client retries with backoff and reports its current state on reconnect; edge reconciles against persisted session. |
| Client process killed mid-session | Session persists on the edge; on reconnect the timer is computed from `started_at` (server clock), not from client-reported elapsed time. |

## 7. Security model

- TLS everywhere: Nginx/uvicorn termination on the cloud, edge-served TLS on the
  LAN. The Electron client pins the edge certificate fingerprint (delivered in the
  pairing string `host:port#sha256fingerprint`), so a rogue LAN host cannot
  impersonate the hub. Pinning is implemented in the main process via
  `setCertificateVerifyProc`; there is no "ignore certificate errors" switch.
- Secrets hashed at rest (`make_password` / SHA-256 for high-entropy tokens) and
  compared in constant time. Edge secret is returned exactly once.
- Remote commands signed and time-limited; clock skew tolerance ±60 s.
- Electron: `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`,
  `webSecurity: true`, no remote content, CSP with no external origins, a strict
  IPC allowlist (`window.gamenet.*` only), executable paths resolved and validated
  in the main process against the admin-managed catalog — never from renderer input.
- Admin: CSRF, session auth, `X-Frame-Options: DENY`, CSP, audit log on every
  mutating action.
- No inbound ports at the site, no router port forwarding, no database exposure.
- Client is treated as a hostile-ish endpoint: it may report state, but never
  computes money and never picks executables.

## 8. Windows deployment decisions

- **Edge**: Python 3.12 + Django 6.1 running under a Windows service wrapper
  (NSSM or WinSW) with PostgreSQL 18 as a Windows service. No Docker, no WSL, no
  Windows Server. Redis is *not* available natively on Windows; the edge uses
  Django Channels' in-process layer with a **single** ASGI worker (validated by a
  startup check), or Memurai if multi-worker is ever needed. The cloud uses Redis.
- **Client**: Electron 22.3.27 (last version supporting Windows 7 SP1), x64 first,
  x86 only after hardware confirmation. Windows 7 requires SP1 + SHA-2 updates +
  TLS 1.2 enablement; the installer checks and reports these.
- The edge binds to a reserved LAN IP; clients are configured with
  `host:port#fingerprint`, never a cloud URL.

## 9. Money rules

- Integer Toman only. `cost = round_half_up(hourly_rate * elapsed_seconds / 3600)`
  implemented with integer arithmetic (`(rate*secs + 1800) // 3600`).
- Tariff snapshot is copied into the session row at start; later price changes
  cannot touch an active session.
- Wallet mutations happen in `transaction.atomic()` with `SELECT ... FOR UPDATE`
  on the wallet row plus a customer-scoped advisory lock, so concurrent starts
  cannot both pass the credit check.
- Ledger is append-only; corrections are reversals referencing the original entry.
- Every charge path is idempotent on `(session_id, entry_type)`.

## 10. Pinned versions

| Component | Version | Reason |
|---|---|---|
| Python | 3.12 (edge), 3.14 (cloud/dev) | 3.12 is the conservative floor; both supported by Django 6.1 |
| Django | 6.1.2 | spec |
| DRF | 3.16.x | spec |
| Channels | 4.3.x | spec |
| PostgreSQL | 18.6 | spec |
| Electron | 22.3.27 | last Win7-compatible |
| React / Vite / TS / Tailwind | 18.3 / 5.x / 5.x / 3.4 | Electron 22 ships Chromium 108; build target `chrome108` |

Exact pins live in `backend/requirements.lock` and `client/pnpm-lock.yaml`.

## 11. Open items requiring physical hardware

These cannot be proven on the Linux dev box and are gated in `docs/PHASE0.md`:
Electron 22 launch/lock/session behaviour on real Windows 7 SP1, DPAPI storage,
certificate pinning against a Windows-served cert, Windows service restart
behaviour, and x86 builds. The code paths are exercised here, but sign-off
requires the Win7/Win10 machines.
