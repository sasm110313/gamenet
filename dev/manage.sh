#!/usr/bin/env bash
# Usage: dev/manage.sh <edge|cloud> <manage.py args...>
set -euo pipefail
cd "$(dirname "$0")/.."
source dev/env.sh
role="${1:?role required}"; shift
cd backend
export GAMENET_ROLE="$role"
export DJANGO_SETTINGS_MODULE="gamenet.settings.$role"
export DATABASE_URL="postgresql://gamenet:gamenet@127.0.0.1:${PG_PORT}/gamenet_${role}"
if [[ "$role" == "cloud" ]]; then
  export CHANNEL_LAYER=redis
  export REDIS_URL="redis://127.0.0.1:${REDIS_PORT}/0"
fi
exec .venv/bin/python manage.py "$@"
