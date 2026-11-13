#!/usr/bin/env bash
# Install or refresh the lightweight GameNet cloud role on an Ubuntu 24.04 host.
#
# Safe to re-run:
#   * existing .env secrets, TLS certificate and nginx site are preserved;
#   * only the GameNet units are restarted;
#   * the existing hammasjedy.ir / masjed / samen apps are never touched.
#
# Run as root from a checkout that already lives at /opt/gamenet.
set -euo pipefail

APP_DIR="${GAMENET_APP_DIR:-/opt/gamenet}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOMAIN="${GAMENET_DOMAIN:-gamenet.hammasjedy.ir}"
ADMIN_EMAIL="${GAMENET_ADMIN_EMAIL:-admin@hammasjedy.ir}"
SERVICE_USER="${GAMENET_USER:-gamenet}"
DB_NAME="${GAMENET_DB_NAME:-gamenet_cloud}"
DB_USER="${GAMENET_DB_USER:-gamenet}"
ENV_FILE="$APP_DIR/.env"
VENV="$APP_DIR/venv"
ADMIN_FILE="/root/gamenet-admin.txt"

log() { printf '\n[gamenet] %s\n' "$*"; }
fail() { printf '\n[gamenet] ERROR: %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fail "run as root"
[[ -f "$REPO_DIR/backend/manage.py" ]] || fail "backend/manage.py not found under $REPO_DIR"

log "installing OS packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  postgresql postgresql-contrib redis-server nginx \
  python3-venv python3-pip certbot python3-certbot-nginx openssl

log "creating service user and directories"
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi
install -d -m 755 "$APP_DIR"
install -d -m 755 "$APP_DIR/static" "$APP_DIR/backend/.runtime"
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/backend" "$APP_DIR/static" "$APP_DIR/backend/.runtime"
chown "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

log "preparing secrets"
if [[ ! -f "$ENV_FILE" ]]; then
  SECRET_KEY="$(openssl rand -hex 32)"
  DB_PASSWORD="$(openssl rand -hex 24)"
  ADMIN_PASSWORD="$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 24)"
  cat >"$ENV_FILE" <<EOF
GAMENET_ROLE=cloud
GAMENET_ENV=production
GAMENET_LOG_LEVEL=INFO
DJANGO_SECRET_KEY=$SECRET_KEY
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=$DOMAIN,127.0.0.1,localhost
DJANGO_CSRF_TRUSTED_ORIGINS=https://$DOMAIN
DJANGO_BEHIND_PROXY=1
DJANGO_USE_X_FORWARDED_HOST=1
DJANGO_SECURE_COOKIES=1
DJANGO_SECURE_SSL_REDIRECT=1
DJANGO_STATIC_ROOT=$APP_DIR/static
DATABASE_URL=postgresql://$DB_USER:$DB_PASSWORD@127.0.0.1:5432/$DB_NAME
CHANNEL_LAYER=redis
REDIS_URL=redis://127.0.0.1:6379/0
DEFAULT_HOURLY_RATE=40000
DEFAULT_CREDIT_LIMIT=60000
DEVICE_COMMAND_TTL_SECONDS=120
SYNC_BATCH_SIZE=100
ADMIN_USERNAME=admin
ADMIN_PASSWORD=$ADMIN_PASSWORD
ADMIN_EMAIL=$ADMIN_EMAIL
EOF
  chown root:"$SERVICE_USER" "$ENV_FILE"
  chmod 640 "$ENV_FILE"
  {
    echo "GameNet cloud administrator"
    echo "username: admin"
    echo "password: $ADMIN_PASSWORD"
    echo "url: https://$DOMAIN/admin/"
    echo "generated: $(date -Is)"
  } >"$ADMIN_FILE"
  chmod 600 "$ADMIN_FILE"
  log "wrote $ADMIN_FILE (mode 600)"
else
  chown root:"$SERVICE_USER" "$ENV_FILE"
  chmod 640 "$ENV_FILE"
  log "reusing existing $ENV_FILE"
fi

DB_PASSWORD="$(
  python3 - "$ENV_FILE" <<'PY'
import sys, urllib.parse
for line in open(sys.argv[1], encoding="utf-8"):
    if line.startswith("DATABASE_URL="):
        url = line.split("=", 1)[1].strip()
        print(urllib.parse.urlsplit(url).password or "")
        break
PY
)"
[[ -n "$DB_PASSWORD" ]] || fail "could not read the database password from $ENV_FILE"

log "creating the PostgreSQL role and database"
if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1; then
  runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c "CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASSWORD'"
else
  runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c "ALTER ROLE $DB_USER WITH PASSWORD '$DB_PASSWORD'"
fi
if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1; then
  runuser -u postgres -- createdb -O "$DB_USER" "$DB_NAME"
fi

log "tuning PostgreSQL for the shared host"
PG_VERSION="$(ls /etc/postgresql | sort -V | tail -1)"
install -d -m 755 "/etc/postgresql/$PG_VERSION/main/conf.d"
install -m 644 "$REPO_DIR/deploy/postgresql-gamenet.conf" \
  "/etc/postgresql/$PG_VERSION/main/conf.d/gamenet.conf"
systemctl enable postgresql >/dev/null
pg_ctlcluster "$PG_VERSION" main restart

log "tuning Redis (WSS fan-out only)"
if [[ ! -f /etc/redis/redis.conf.gamenet-orig ]]; then
  cp -a /etc/redis/redis.conf /etc/redis/redis.conf.gamenet-orig
fi
install -m 640 -o redis -g redis "$REPO_DIR/deploy/redis-gamenet.conf" /etc/redis/redis.conf
systemctl enable redis-server >/dev/null
systemctl restart redis-server

log "installing Python dependencies"
if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV"
fi
if [[ -n "${GAMENET_SITEPACKAGES:-}" ]]; then
  # Fully offline path: a pre-resolved site-packages tree built on a matching
  # Linux/cp312 host (uv pip install --offline --target ...).
  SITE_DIR="$VENV/lib/python3.12/site-packages"
  install -d "$SITE_DIR"
  cp -a "$GAMENET_SITEPACKAGES/." "$SITE_DIR/"
  "$VENV/bin/python" - <<'PY'
import channels, cryptography, django, psycopg, uvicorn
print(f"preloaded django={django.get_version()} psycopg={psycopg.__version__}")
PY
elif [[ -n "${GAMENET_WHEELHOUSE:-}" ]]; then
  # Offline/air-gapped path: wheels pre-fetched on a build host.
  "$VENV/bin/pip" install --quiet --no-index --find-links "$GAMENET_WHEELHOUSE" \
    -r "$REPO_DIR/deploy/requirements.prod.txt"
else
  "$VENV/bin/pip" install --quiet --upgrade pip wheel
  "$VENV/bin/pip" install --quiet --timeout 120 --retries 10 \
    -r "$REPO_DIR/deploy/requirements.prod.txt"
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$VENV"

log "applying migrations and static files"
cd "$APP_DIR/backend"
runuser -u "$SERVICE_USER" -- env DJANGO_SETTINGS_MODULE=gamenet.settings.cloud \
  "$VENV/bin/python" manage.py migrate --noinput
runuser -u "$SERVICE_USER" -- env DJANGO_SETTINGS_MODULE=gamenet.settings.cloud \
  "$VENV/bin/python" manage.py collectstatic --noinput --clear
runuser -u "$SERVICE_USER" -- env DJANGO_SETTINGS_MODULE=gamenet.settings.cloud \
  "$VENV/bin/python" manage.py check

log "bootstrapping the administrator"
ADMIN_USERNAME="$(grep '^ADMIN_USERNAME=' "$ENV_FILE" | cut -d= -f2-)"
ADMIN_PASSWORD="$(grep '^ADMIN_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)"
ADMIN_EMAIL_ENV="$(grep '^ADMIN_EMAIL=' "$ENV_FILE" | cut -d= -f2-)"
runuser -u "$SERVICE_USER" -- env DJANGO_SETTINGS_MODULE=gamenet.settings.cloud \
  "$VENV/bin/python" manage.py bootstrap_cloud \
  --username "${ADMIN_USERNAME:-admin}" \
  --password "${ADMIN_PASSWORD:-}" \
  --email "${ADMIN_EMAIL_ENV:-$ADMIN_EMAIL}"

log "installing the GameNet systemd unit"
install -m 644 "$REPO_DIR/deploy/gamenet-cloud.service" /etc/systemd/system/gamenet-cloud.service
systemctl daemon-reload
systemctl enable gamenet-cloud >/dev/null
systemctl restart gamenet-cloud

log "installing the daily backup timer"
install -m 750 "$REPO_DIR/deploy/backup-gamenet.sh" /usr/local/sbin/gamenet-backup
install -m 644 "$REPO_DIR/deploy/gamenet-backup.service" /etc/systemd/system/gamenet-backup.service
install -m 644 "$REPO_DIR/deploy/gamenet-backup.timer" /etc/systemd/system/gamenet-backup.timer
systemctl daemon-reload
systemctl enable --now gamenet-backup.timer >/dev/null

log "installing the isolated Nginx site"
if [[ ! -f /etc/nginx/sites-available/gamenet ]]; then
  sed "s/__DOMAIN__/$DOMAIN/g" "$REPO_DIR/deploy/nginx-gamenet.conf" \
    > /etc/nginx/sites-available/gamenet
fi
ln -sf ../sites-available/gamenet /etc/nginx/sites-enabled/gamenet
nginx -t
systemctl reload nginx

log "issuing a TLS certificate for $DOMAIN"
if [[ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]]; then
  if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$ADMIN_EMAIL" --redirect; then
    log "certificate issued"
  else
    log "WARNING: certbot failed; the site is still available over HTTP"
  fi
else
  log "existing certificate found; leaving it alone"
fi
nginx -t && systemctl reload nginx

log "waiting for the service"
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:18443/healthz" >/dev/null 2>&1; then
    log "healthz OK"
    break
  fi
  sleep 1
done
curl -fsS "http://127.0.0.1:18443/healthz" || fail "health check failed; run: journalctl -u gamenet-cloud -n 80"
systemctl --no-pager --lines=0 status gamenet-cloud || true
log "done; admin credentials: $ADMIN_FILE"
