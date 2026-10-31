#!/usr/bin/env bash
# Apply migrations to both databases. The schema is identical by design.
set -euo pipefail
cd "$(dirname "$0")/.."
source dev/env.sh
cd backend

run() {
  local role="$1" url="$2"
  echo "[..] migrate $role"
  GAMENET_ROLE="$role" DJANGO_SETTINGS_MODULE="gamenet.settings.$role" DATABASE_URL="$url" \
    .venv/bin/python manage.py migrate --noinput
}

run edge "postgresql://gamenet:gamenet@127.0.0.1:${PG_PORT}/gamenet_edge"
run cloud "postgresql://gamenet:gamenet@127.0.0.1:${PG_PORT}/gamenet_cloud"

echo "[..] bootstrap cloud admin + config"
GAMENET_ROLE=cloud DJANGO_SETTINGS_MODULE=gamenet.settings.cloud \
  DATABASE_URL="postgresql://gamenet:gamenet@127.0.0.1:${PG_PORT}/gamenet_cloud" \
  .venv/bin/python manage.py bootstrap_cloud "$@"
