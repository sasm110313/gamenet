#!/usr/bin/env bash
# Daily compressed PostgreSQL backup for the GameNet cloud database.
# Installed at /usr/local/sbin/gamenet-backup and driven by gamenet-backup.timer.
set -euo pipefail
umask 077

BACKUP_DIR="${GAMENET_BACKUP_DIR:-/var/backups/gamenet}"
DB_NAME="${GAMENET_DB_NAME:-gamenet_cloud}"
KEEP_DAYS="${GAMENET_BACKUP_KEEP_DAYS:-14}"
STAMP="$(date +%Y-%m-%d-%H%M%S)"
FILE="$BACKUP_DIR/${DB_NAME}-${STAMP}.dump"

install -d -m 700 "$BACKUP_DIR"
# pg_dump runs as the postgres OS user but writes to stdout; the root shell owns
# the destination file, so the backup directory stays root-only.
runuser -u postgres -- pg_dump --format=custom --compress=6 --no-owner \
  --dbname="$DB_NAME" >"$FILE"
chmod 600 "$FILE"

# Keep the last N days. A failed dump exits above, so old backups survive.
find "$BACKUP_DIR" -type f -name "${DB_NAME}-*.dump" -mtime "+${KEEP_DAYS}" -delete
