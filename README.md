# GameNet — Cyber Cafe / Gaming Center Management System

Hybrid edge-cloud management for Windows gaming clients: cloud backend, on-site
Control Hub (Windows 10), and an Electron client for Windows 7 SP1.

**Status: Phase 1 — customers, groups/tariffs, wallets, append-only ledger and
gaming sessions are implemented on the edge and projected read-only to the
cloud. The backend suite passes 109 tests; the Phase 0 connectivity proof passed
10/10 on the Linux dev host. Windows hardware acceptance is still pending.**

See [docs/PHASE1.md](docs/PHASE1.md) for the Phase 1 scope and money/session
rules, [docs/PHASE0.md](docs/PHASE0.md) for the connectivity proof and the
on-site checklist, and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the
design.

## Repository layout

```
backend/            Django modular monolith (one codebase, two roles)
  gamenet/          project settings, ASGI/URL wiring (cloud + edge)
  apps/             business + transport apps
client/             Electron 22.3.27 + React + TypeScript + Tailwind client
docs/               architecture, phase evidence, Windows checklists
dev/                local dev/proof tooling (PostgreSQL, Redis, TLS certs)
scripts/            proof and ops scripts
```

## Phase 1 features

Edge (the only writer of these facts):

- Customers with a unique phone per edge, optional billing group, credit limit,
  notes and activation state. Groups inherit a tariff; without one, the configured
  default of 40,000 Toman/hour applies.
- Wallets with deposits, manual adjustments and reversal entries. Corrections are
  new ledger rows that reference the original; nothing is updated or deleted.
- Gaming sessions with a tariff snapshot at start, one active session per device,
  and multiple concurrent sessions per customer. Stopping charges exact elapsed
  time with integer half-up Toman rounding.
- Start reserves one billable hour per active session against
  `balance + credit_limit`; stop may exceed the limit because elapsed time is
  already a fact.
- Every business mutation and its outbox event commit in the same transaction, so
  an acknowledged fact can never be missing from the queue.

Cloud (read-only replica and remote control):

- Read-only customer, session, ledger and pricing pages fed by edge events.
- Projections fail closed: a customer group that references an unknown tariff, a
  customer that references an unknown group, or a ledger entry that references an
  unknown customer/session rejects the event. The edge keeps retrying; the cloud
  never records a partial financial fact.
- Duplicate delivery is idempotent on `(edge, event_id)`; sequence reuse and
  per-aggregate regression are rejected.

## Run the Phase 0 proof

```bash
cp .env.example .env        # set ADMIN_PASSWORD; review ports
./dev/setup_local.sh        # venv, deps, local PostgreSQL 18 + Redis, TLS certs
./dev/migrate.sh            # migrate both roles and create the admin
```

Start the three long-running processes in separate terminals:

```bash
./dev/run_cloud.sh                      # terminal 1 — cloud HTTPS/WSS :18443
./dev/run_edge.sh                       # terminal 2 — edge HTTPS/WSS :19443
./dev/manage.sh edge run_edge_worker    # terminal 3 — the single edge worker
```

Build and pair the Electron client (dev host):

```bash
cd client
npm ci
npm run build
GAMENET_DEV_UNPAIR=1 npm run dev -- --no-sandbox --remote-debugging-port=9223
```

Pair with the edge host and pinned leaf-certificate fingerprint, e.g.
`127.0.0.1:19443#<sha256-from-dev/certs>`. The fingerprint is printed by
`./scripts/make_certs.sh`.

Run the acceptance proof:

```bash
backend/.venv/bin/python scripts/phase0_proof.py --client-device PC-06
```

Evidence is written to `docs/evidence/phase0.json`, `.md` and two client
screenshots. The runner stops and restarts the cloud to prove offline queueing;
it does not print or store device tokens or edge secrets.

Local dashboards:

- Edge: `https://127.0.0.1:19443/` — overview, devices, customers, sessions,
  ledger, pricing and cloud health.
- Cloud: `https://127.0.0.1:18443/` — overview, edges, commands, events, config,
  and read-only customers, sessions, ledger and pricing.

## Tests

```bash
cd backend && .venv/bin/pytest
cd client && npm run typecheck && npm run build
```

## Non-negotiable constraints

- Cloud synchronization ships in Phase 0, not later.
- Money is integer Toman arithmetic only; ledger is append-only.
- Edge is the authority for local sessions and financial records; the cloud is a
  replica, not a last-write-wins peer.
- Windows 7 SP1 clients run Electron 22.3.27 (EOL, accepted and mitigated).
- No CDN assets, no hardcoded hosts or secrets, `.env` driven configuration.
