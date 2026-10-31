#!/usr/bin/env bash
# One-time local setup for the Phase 0 proof: Python deps, PostgreSQL 18, Redis,
# and a local CA + TLS certs. Linux dev only.
set -euo pipefail
source "$(dirname "$0")/env.sh"
mkdir -p "$ART"

# --- Python ---
cd "$ROOT/backend"
if [[ ! -x .venv/bin/python ]]; then
  uv venv --python 3.12 .venv
fi
uv pip install --python .venv/bin/python -q -r requirements.txt
echo "[ok] python deps"

# --- PostgreSQL 18 (extracted RPMs; no root needed on Fedora) ---
if [[ ! -x "$PGBIN/postgres" ]]; then
  echo "[..] fetching PostgreSQL 18 RPMs"
  tmp="$(mktemp -d)"
  (cd "$tmp" && dnf download --destdir . postgresql-server postgresql postgresql-private-libs >/dev/null)
  mkdir -p "$ART/pg"
  for f in "$tmp"/postgresql-*x86_64.rpm "$tmp"/postgresql-private-libs-*x86_64.rpm; do
    (cd "$ART/pg" && rpm2cpio "$f" | cpio -idm --quiet)
  done
  rm -rf "$tmp"
fi
if [[ ! -d "$PGDATA" ]]; then
  LD_LIBRARY_PATH="$ART/pg/lib64:$ART/pg/lib" "$PGBIN/initdb" -D "$PGDATA" -U postgres \
    --auth-local=trust --auth-host=scram-sha-256 >/dev/null
  # Dev-only cluster bound to loopback; keep host auth simple for tooling.
  printf 'host all all 127.0.0.1/32 trust\n' | cat - "$PGDATA/pg_hba.conf" > "$PGDATA/pg_hba.new"
  mv "$PGDATA/pg_hba.new" "$PGDATA/pg_hba.conf"
fi
start_pg
"$PGBIN/psql" -h 127.0.0.1 -p "$PG_PORT" -U postgres -v ON_ERROR_STOP=1 <<'SQL' >/dev/null
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'gamenet') THEN
    CREATE ROLE gamenet LOGIN PASSWORD 'gamenet';
  END IF;
END $$;
SQL
for db in gamenet_cloud gamenet_edge; do
  "$PGBIN/psql" -h 127.0.0.1 -p "$PG_PORT" -U postgres -tAc \
    "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1 || \
    "$PGBIN/psql" -h 127.0.0.1 -p "$PG_PORT" -U postgres -c "CREATE DATABASE $db OWNER gamenet" >/dev/null
done
echo "[ok] postgres on 127.0.0.1:$PG_PORT (dbs: gamenet_cloud, gamenet_edge)"

# --- Redis (channel layer for cloud) ---
start_redis
echo "[ok] redis on 127.0.0.1:$REDIS_PORT"

# --- TLS ---
"$ROOT/scripts/make_certs.sh"
echo "[ok] certs in dev/certs"

echo
echo "Next: cp .env.example .env && ./dev/migrate.sh && ./dev/run_cloud.sh / ./dev/run_edge.sh"
