# Phase 0 — Connectivity Proof

Status: **software proof passed (10/10) on the Linux development host.**
Windows 10 edge and Windows 7 SP1 client hardware acceptance is still **pending**
and is listed as an explicit checklist at the end of this document.

Phase 0 exists to prove the hard part before any session, wallet or billing code
is written: a real cloud can reach a real edge, the edge can reach a real
Electron client, every hop survives a cloud outage, and financial events cannot
be duplicated or reordered.

## 1. Topology used for this run

```
Electron 22.3.27 (PC-06)          Edge (Django, GAMENET_ROLE=edge)        Cloud (Django, GAMENET_ROLE=cloud)
┌──────────────────────┐  WSS    ┌───────────────────────────────┐  WSS   ┌──────────────────────────────┐
│ pinned leaf cert     │────────▶│ PostgreSQL 18 (authority)     │───────▶│ PostgreSQL 18 (replica)      │
│ local token (DPAPI)  │◀────────│ outbox + inbound command ledger│◀───────│ Redis channel layer          │
│ RTL React renderer   │  HTTPS  │ in-memory channel layer       │ HTTPS  │ admin dashboards             │
└──────────────────────┘         └───────────────────────────────┘        └──────────────────────────────┘
        127.0.0.1:19443                    127.0.0.1:18443
```

Local ports used by the dev harness:

| Service | Address |
|---|---|
| Cloud HTTPS/WSS | `https://127.0.0.1:18443` |
| Edge HTTPS/WSS | `https://127.0.0.1:19443` |
| PostgreSQL 18 | `127.0.0.1:55432` |
| Redis | `127.0.0.1:56379` |
| Electron DevTools (proof only) | `127.0.0.1:9223` |

Both dashboards use the same administrator credentials from `.env`. The edge
identity is `01a18e45-00ea-7f5b-8631-0d6406670e55`, registered with the cloud and
authenticated with the `Edge <uuid>.<secret>` header.

## 2. Result

Evidence produced by the run:

- [`docs/evidence/phase0.json`](evidence/phase0.json) — machine-readable details
- [`docs/evidence/phase0.md`](evidence/phase0.md) — readable report
- [`docs/evidence/phase0-client-unlocked.png`](evidence/phase0-client-unlocked.png)
- [`docs/evidence/phase0-client-locked.png`](evidence/phase0-client-locked.png)

Run window: `2026-10-31T06:12:20Z` → `2026-10-31T06:13:10Z` (50.33 s).

| # | Required proof | Result | Evidence in `phase0.json` |
|---|---|---|---|
| 1 | Edge registers with cloud and authenticates | ✅ | Cloud `EdgeNode` exists; SHA-256 credential hash is 64 chars; command public key present; edge-authenticated `/api/v1/edge/config` returns HTTP 200. |
| 2 | Device registers over edge HTTPS | ✅ | Edge issues a one-time token; the device appears in the cloud as `is_replica=true`, written only through ingest. |
| 3 | Device heartbeat works | ✅ | WSS `welcome` + `heartbeat_ack`, then REST heartbeat; `last_heartbeat_at` is persisted on the edge. |
| 4 | Local edge dashboard shows status | ✅ | Logged-in `/devices/?q=PROOF-PC-…` shows the device and `آنلاین`. |
| 5 | Cloud dashboard shows status | ✅ | Logged-in cloud edge page and overview show the replicated device and the edge name `سالن اصلی`. |
| 6 | Remote command cloud → edge | ✅ | Dashboard action creates `edge.ping`; cloud row ends `ACKNOWLEDGED` with `pong=true`; edge inbound ledger ends `SUCCEEDED`. |
| 7 | Command forwarded to the real client | ✅ | `client.unlock`, `client.lock`, `client.ping` all end `ACKNOWLEDGED`; the Electron UI is captured on both screens; the edge `DeviceCommand` row is acknowledged. |
| 8 | Edge → cloud event | ✅ | `edge.test` emitted by the edge command executor reaches the cloud with `origin=cloud_command`, status `APPLIED`. |
| 9 | Duplicate-event protection | ✅ | Replaying the same `event_id` returns `duplicates=[…]` and does not increase the event count; reusing the same `local_sequence` with a new id is rejected with `sequence already used`. |
| 10 | Offline queue and later sync | ✅ | The cloud process is stopped; a new event stays `PENDING` with no cloud ack; after the cloud returns it becomes `SYNCED` with attempts=1 and appears in the cloud replica. |

The command round-trip in check 7 took ~33 s for three commands because the
edge worker executes/pulls commands on its 2 s cycle and each command needs a
worker cycle to drain the resulting `command.result` event. This is correctness
first; Phase 1 will measure and tune operator-perceived latency.

## 3. What is actually verified

### Trust boundaries

- The Electron client pins the edge leaf certificate SHA-256
  (`28919228D69B275637410AC9BBFE74DC64EA9363534E7063AF84FB2916C8A21B`).
  A wrong pin is rejected before the device token leaves the process.
- The edge authenticates to the cloud with a per-edge secret and verifies every
  remote command's Ed25519 signature, expiry and nonce before execution.
- Remote commands are exactly-once on the edge: `InboundRemoteCommand.command_id`
  is unique and is claimed with a row lock before any side effect.
- Device commands are two-stage: the edge reports `forwarded`, and only the
  client's own acknowledgement produces the final `succeeded` / `failed` result.
- Dashboards require an authenticated Django session and CSRF for every POST.

### Data integrity

- Cloud ingest dedupes on `(edge, event_id)`.
- Reusing a `local_sequence` for a different event id is rejected.
- Per-aggregate regression is rejected; gaps are allowed because a rolled-back
  transaction may legitimately leave a hole.
- The edge outbox is strict FIFO by `local_sequence`; a `FAILED` head blocks the
  stream rather than letting financial events overtake each other.
- The cloud ack watermark only advances over a contiguous prefix.
- Check 9 confirms the cloud event count is unchanged after duplicate replay.

### Offline behaviour

- The proof stops the cloud process with `SIGTERM`, emits a real edge event, and
  observes it as `PENDING` with `attempts=0` while the cloud is down.
- When the cloud returns, the edge worker retries and the event becomes `SYNCED`.
- The LAN client keeps talking to the edge throughout; the cloud is not in the
  client's data path.

## 4. Reproduce

Prerequisites: Linux dev host with `uv`, `dnf`, PostgreSQL client tools and Redis,
or an already provisioned equivalent. The commands below are exactly what this
run used.

```bash
cd /home/sasm/Documents/GitHub/gamenet
cp .env.example .env            # set ADMIN_PASSWORD and review ports
./dev/setup_local.sh            # venv, PostgreSQL 18, Redis, local CA + TLS certs
./dev/migrate.sh                # migrate both roles + bootstrap cloud admin
```

Terminal 1 — cloud:

```bash
./dev/run_cloud.sh
```

Terminal 2 — edge web process:

```bash
./dev/run_edge.sh
```

Terminal 3 — the single edge worker (outbox, command pull, heartbeat, config):

```bash
./dev/manage.sh edge run_edge_worker
```

Pair and run the Electron client (dev host, no production packaging):

```bash
cd client
npm ci
npm run build
GAMENET_DEV_UNPAIR=1 npm run dev -- --no-sandbox --remote-debugging-port=9223
```

Pair with:

```
127.0.0.1:19443#28919228D69B275637410AC9BBFE74DC64EA9363534E7063AF84FB2916C8A21B
```

The fingerprint is the edge leaf certificate's SHA-256. It is printed by
`scripts/make_certs.sh`; never copy a fingerprint from an untrusted channel.

Run the acceptance proof:

```bash
backend/.venv/bin/python scripts/phase0_proof.py --client-device PC-06
```

The script is intentionally black-box: it logs into both dashboards, drives the
Electron renderer through CDP, stops/restarts the cloud, and queries PostgreSQL
through the Django shell only to verify what the HTTP/WSS flows produced. It
redacts credentials and never writes a device token or edge secret to evidence.

## 5. Defects found and fixed during Phase 0

### Redis client timeout killed every idle WSS after 5 seconds

`channels-redis 4.3.0` expects `BRPOP(timeout=5)` to return `None` when no message
arrives. `redis-py 8.1.0` raises `redis.exceptions.TimeoutError` instead, which
propagated out of the Channels dispatch loop and closed every idle edge WSS with
code 1006. The edge reconnected, but every connection lasted only five seconds,
so cloud-pushed commands were unreliable.

Fix: pin `redis==5.2.1` in `backend/requirements.txt`. Verified by holding an
authenticated edge WSS idle for more than 5 seconds and by the full proof run
(checks 6–8 depend on a stable cloud → edge channel).

### Dashboard login could silently land on the login page

The proof now asserts that the post-login URL is not `/admin/login/`, so a bad
password cannot produce a false-positive "dashboard works" result.

## 6. Not covered by this run

This run is real software evidence on a Linux host. It does **not** prove Windows
hardware behaviour. The following acceptance work remains and must be executed
on site before Phase 0 is closed for delivery.

### Windows 10 edge (no Windows Server, no Docker, no WSL)

- [ ] Clean Windows 10 Pro 22H2 x64 install; document build and patch level.
- [ ] Python 3.12 + PostgreSQL 18 installed natively; no container runtime.
- [ ] Edge service runs under NSSM/WinSW and starts automatically after reboot.
- [ ] Edge worker runs as a **single** service instance; duplicate workers are refused.
- [ ] PostgreSQL starts automatically and survives a hard reboot.
- [ ] Edge TLS certificate and CA installed; LAN clients trust only the intended CA.
- [ ] Windows Firewall allows 19443 from the LAN and nothing else inbound from the internet.
- [ ] Edge registration to the real cloud over HTTPS succeeds.
- [ ] Cloud stopped → local dashboards and client commands continue; outbox pending count rises.
- [ ] Cloud restored → outbox drains; cloud replica catches up.
- [ ] Service restart during an active client connection: client reconnects and remains locked until commanded.
- [ ] Disk-full and clock-skew behaviour are recorded (no silent financial loss).

### Windows 7 SP1 client (Electron 22.3.27)

- [ ] Clean Windows 7 SP1 x64 with SHA-2/root-certificate updates; document patch level.
- [ ] Production build launches without a console window and without network access to CDNs.
- [ ] `contextIsolation=true`, `sandbox=true`, `nodeIntegration=false` verified in the packaged app.
- [ ] Strict preload IPC allowlist verified; renderer cannot invoke arbitrary shell commands.
- [ ] Pairing rejects a wrong certificate fingerprint before the token is sent.
- [ ] Device token is stored with `safeStorage`/DPAPI; restarting the app keeps the pairing; plaintext fallback is refused on Windows.
- [ ] Pull the LAN cable: client locks immediately and shows the disconnected state.
- [ ] Restore the LAN: client reconnects and returns to the hub-commanded state.
- [ ] Cloud lock/unlock/ping reaches the client while the internet is unavailable (LAN-only operation).
- [ ] x86 (32-bit) and x64 builds are produced and installed on the target hardware.
- [ ] RTL layout, Vazirmatn font and Tabler assets render offline at the venue's screen resolution.
- [ ] Uninstall/reinstall does not leave a usable orphaned token.

### Cross-cutting

- [ ] A real cable pull between edge and cloud, not a process stop.
- [ ] A cloud restart under load with a deep outbox backlog.
- [ ] Clock skew beyond the command skew window is rejected and logged.
- [ ] Backup/restore of the edge database reproduces the same cloud replica state.

## 7. Phase 0 exit criteria

Phase 0 can be marked complete for delivery when:

1. This 10/10 software proof is reproducible from a clean checkout.
2. The Windows 10 edge checklist passes on the actual venue management PC.
3. The Windows 7 SP1 client checklist passes on at least one actual gaming PC.
4. The evidence bundle (JSON, Markdown, screenshots, hardware sign-off) is
   committed and linked from the project README.

Until then, the correct status is **software proof complete, hardware acceptance
pending** — not "Phase 0 delivered".
