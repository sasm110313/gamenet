#!/usr/bin/env bash
# GameNet Cloud — safe in-place update (run as root on the cloud server).
# Usage:  bash deploy_cloud_update.sh [path/to/gamenet-cloud-0.2.10.tar.gz]
set -euo pipefail

APP="/opt/gamenet"
PKG="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/gamenet-cloud-0.2.10.tar.gz}"
TS="$(date +%Y%m%d-%H%M%S)"
TMP="/tmp/gamenet_cloud_update"

[[ $EUID -eq 0 ]] || { echo "run as root"; exit 1; }
[[ -f "$PKG" ]] || { echo "package not found: $PKG"; exit 1; }
[[ -f "$APP/backend/manage.py" ]] || { echo "no installation at $APP"; exit 1; }

echo "[1/7] Backing up database, code and .env ..."
sudo -u postgres pg_dump -Fc gamenet_cloud > "/root/gamenet_cloud-$TS.dump"
tar czf "/root/gamenet_backend-$TS.tgz" --exclude="__pycache__" --exclude="*.pyc" -C "$APP" backend
cp "$APP/.env" "/root/gamenet_env-$TS"
echo "      backup tag: $TS"

systemctl stop gamenet-cloud

echo "[2/7] Extracting package ..."
rm -rf "$TMP"; mkdir -p "$TMP"
tar xzf "$PKG" -C "$TMP"
[[ -d "$TMP/backend" ]] || { echo "bad package (backend missing)"; exit 1; }

echo "[3/7] Syncing backend (data and .env are preserved) ..."
rsync -a --exclude "data" --exclude ".runtime" --exclude "*.sqlite3*" "$TMP/backend/" "$APP/backend/"

echo "[4/7] Syncing deploy files ..."
if [[ -d "$TMP/deploy" ]]; then rsync -a "$TMP/deploy/" "$APP/deploy/"; fi
chown -R gamenet:gamenet "$APP/backend"

echo "Installing required runtime dependencies ..."
if ! sudo -u gamenet /opt/gamenet/venv/bin/python -m pip install -r "$APP/deploy/requirements.prod.txt"; then
  echo "WARNING: dependency installation failed; the health check decides whether to continue."
fi
if ! sudo -u gamenet /opt/gamenet/venv/bin/python -c "import websockets"; then
  echo "WARNING: websockets is missing; the edge role needs it, the health check decides for the cloud."
fi

echo "[5/7] Migrating database ..."
cd "$APP/backend"
sudo -u gamenet bash -c 'set -a; . /opt/gamenet/.env; set +a; /opt/gamenet/venv/bin/python manage.py migrate --noinput'

echo "[6/7] Collecting static files ..."
sudo -u gamenet bash -c 'set -a; . /opt/gamenet/.env; set +a; /opt/gamenet/venv/bin/python manage.py collectstatic --noinput' | tail -1

echo "[7/7] Restarting and health check ..."
systemctl restart gamenet-cloud
sleep 4
CODE="$(curl -s -o /dev/null -w '%{http_code}' -H 'X-Forwarded-Proto: https' http://127.0.0.1:18443/healthz)"
systemctl is-active gamenet-cloud
echo "healthz => $CODE"
[[ "$CODE" == "200" ]] || { echo "HEALTH CHECK FAILED — restore from /root/gamenet_backend-$TS.tgz"; exit 1; }
echo "Done. Backup tag: $TS"
