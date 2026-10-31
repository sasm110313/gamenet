#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source dev/env.sh
cd backend
export GAMENET_ROLE=cloud
export DJANGO_SETTINGS_MODULE=gamenet.settings.cloud
export DATABASE_URL="postgresql://gamenet:gamenet@127.0.0.1:${PG_PORT}/gamenet_cloud"
export CHANNEL_LAYER=redis
export REDIS_URL="redis://127.0.0.1:${REDIS_PORT}/0"
exec .venv/bin/uvicorn gamenet.asgi:application \
  --host 0.0.0.0 --port "${CLOUD_PORT}" \
  --ssl-keyfile "$CERTS/cloud.key" --ssl-certfile "$CERTS/cloud.pem" \
  --ws websockets --log-level info
