# Deploying the GameNet cloud

The cloud role is a single uvicorn process with PostgreSQL and Redis on the same
host. It is designed for the shared 1 vCPU / ~1 GiB server; it does not touch the
existing `masjed` or `samen` apps.

## First install

1. Copy the repository to `/opt/gamenet` without `.env`, `.git`, virtualenvs or
   client build output.
2. Run as root:

```bash
bash /opt/gamenet/deploy/install_cloud.sh
```

The script is idempotent. It:

- installs PostgreSQL, Redis, Nginx, Certbot and Python;
- creates the `gamenet` service user and the `gamenet_cloud` database;
- generates `/opt/gamenet/.env` (mode `640`) and `/root/gamenet-admin.txt`
  (mode `600`) on first run;
- installs pinned runtime packages, applies migrations and collects static files;
- installs `gamenet-cloud.service` and the daily `gamenet-backup.timer`;
- installs a separate Nginx site and requests a Let's Encrypt certificate if one
  is not already present.

## Offline / slow PyPI hosts

If the server cannot reach PyPI, build a matching site-packages tree on a Linux
host with Python 3.12:

```bash
uv pip install --offline --python 3.12 --target /tmp/prod-site \
  -r deploy/requirements.prod.txt
rsync -az /tmp/prod-site/ root@server:/opt/gamenet/wheels/prod-site/
```

Then run the installer with:

```bash
GAMENET_SITEPACKAGES=/opt/gamenet/wheels/prod-site \
  bash /opt/gamenet/deploy/install_cloud.sh
```

A wheelhouse works too:

```bash
GAMENET_WHEELHOUSE=/opt/gamenet/wheels \
  bash /opt/gamenet/deploy/install_cloud.sh
```

## Day-to-day

```bash
systemctl status gamenet-cloud
journalctl -u gamenet-cloud -n 100 --no-pager
curl -sS -H 'X-Forwarded-Proto: https' http://127.0.0.1:18443/healthz
systemctl list-timers gamenet-backup.timer
```

Backups are written to `/var/backups/gamenet/gamenet_cloud-*.dump` (custom
format, compressed) and older than 14 days are removed.

## Re-deploying code

```bash
rsync -az --exclude .env --exclude .git --exclude backend/.venv \
  ./ root@server:/opt/gamenet/
ssh root@server 'cd /opt/gamenet/backend && \
  runuser -u gamenet -- env DJANGO_SETTINGS_MODULE=gamenet.settings.cloud \
  /opt/gamenet/venv/bin/python manage.py migrate --noinput && \
  runuser -u gamenet -- env DJANGO_SETTINGS_MODULE=gamenet.settings.cloud \
  /opt/gamenet/venv/bin/python manage.py collectstatic --noinput && \
  systemctl restart gamenet-cloud'
```

Do not replace files inside the running virtualenv in place; stop/restart the
service around package changes, otherwise a running process can receive `SIGBUS`.
