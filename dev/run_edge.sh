#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source dev/env.sh
cd backend
export GAMENET_ROLE=edge
export DJANGO_SETTINGS_MODULE=gamenet.settings.edge
export DATABASE_URL="postgresql://gamenet:gamenet@127.0.0.1:${PG_PORT}/gamenet_edge"
export CHANNEL_LAYER=memory
exec .venv/bin/uvicorn gamenet.asgi:application \
  --host "${EDGE_LAN_BIND:-127.0.0.1}" --port "${EDGE_LAN_PORT}" \
  --ssl-keyfile "$CERTS/edge.key" --ssl-certfile "$CERTS/edge.pem" \
  --ws websockets --log-level info
