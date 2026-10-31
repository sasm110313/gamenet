#!/usr/bin/env bash
# Shared paths/env for local development on Linux. Production deployment does not
# use this file; the Windows edge and the Linux cloud each have their own setup.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ROOT
export ART="$ROOT/.artifacts"
export PGBIN="$ART/pg/bin"
export PGDATA="$ART/pgdata"
export PG_PORT="${PG_PORT:-55432}"
export REDIS_PORT="${REDIS_PORT:-56379}"
export CLOUD_PORT="${CLOUD_PORT:-18443}"
export EDGE_PORT="${EDGE_PORT:-19443}"
export CERTS="$ROOT/dev/certs"
if [[ -d "$ART/pg/lib64" ]]; then
  export LD_LIBRARY_PATH="$ART/pg/lib64:$ART/pg/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

pg_running() { [[ -f "$PGDATA/postmaster.pid" ]] && "$PGBIN/pg_ctl" -D "$PGDATA" status >/dev/null 2>&1; }
redis_running() { [[ -f "$ART/redis.pid" ]] && kill -0 "$(cat "$ART/redis.pid")" 2>/dev/null; }

start_pg() {
  if pg_running; then return 0; fi
  LD_LIBRARY_PATH="$ART/pg/lib64:$ART/pg/lib" "$PGBIN/pg_ctl" -D "$PGDATA" -l "$ART/postgres.log" \
    -o "-p $PG_PORT -k $ART -c listen_addresses=127.0.0.1" start >/dev/null
  for _ in $(seq 1 30); do
    if "$PGBIN/pg_isready" -h 127.0.0.1 -p "$PG_PORT" >/dev/null 2>&1; then return 0; fi
    sleep 0.5
  done
  echo "postgres failed to start; see $ART/postgres.log" >&2; return 1
}

start_redis() {
  if redis_running; then return 0; fi
  redis-server --port "$REDIS_PORT" --bind 127.0.0.1 --save '' --appendonly no \
    --daemonize yes --pidfile "$ART/redis.pid" --logfile "$ART/redis.log" \
    --dir "$ART"
  for _ in $(seq 1 20); do
    redis-cli -p "$REDIS_PORT" ping >/dev/null 2>&1 && return 0
    sleep 0.25
  done
  echo "redis failed to start; see $ART/redis.log" >&2; return 1
}

stop_local_services() {
  pg_running && LD_LIBRARY_PATH="$ART/pg/lib64:$ART/pg/lib" "$PGBIN/pg_ctl" -D "$PGDATA" stop -m fast >/dev/null || true
  redis_running && kill "$(cat "$ART/redis.pid")" 2>/dev/null || true
}
