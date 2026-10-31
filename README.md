# GameNet — Cyber Cafe / Gaming Center Management System

Hybrid edge-cloud management for Windows gaming clients: cloud backend, on-site
Control Hub (Windows 10), and an Electron client for Windows 7 SP1.

**Status: Phase 0 — software connectivity proof passed 10/10 on the Linux dev
host; Windows hardware acceptance pending.** See
[docs/PHASE0.md](docs/PHASE0.md) for the proof, evidence and the on-site
checklist, and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design.

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

- Edge: `https://127.0.0.1:19443/`
- Cloud: `https://127.0.0.1:18443/`

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
