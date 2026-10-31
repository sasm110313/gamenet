#!/usr/bin/env bash
# Stop local dev processes started by run_cloud.sh / run_edge.sh / run_edge_worker.
set -uo pipefail
cd "$(dirname "$0")/.."
source dev/env.sh

for port in "${CLOUD_PORT}" "${EDGE_PORT}"; do
  pid="$(ss -ltnpH "sport = :${port}" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | head -1)"
  if [[ -n "${pid}" ]]; then
    kill "${pid}" 2>/dev/null && echo "stopped listener on ${port} (pid ${pid})"
  fi
done

for pid in $(pgrep -f "manage.py run_edge_worker" 2>/dev/null); do
  kill "${pid}" 2>/dev/null && echo "stopped edge worker (pid ${pid})"
done
