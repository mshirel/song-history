#!/bin/sh
# backup.sh — create a verified SQLite dump and write a .last_success sentinel.
#
# Usage: backup.sh <db_path> <backup_dir>
#
# On success:
#   - Writes <backup_dir>/worship-YYYYMMDD-HHMMSS.sql.gz (integrity-checked)
#   - Writes <backup_dir>/.last_success with the timestamp
#   - Exits 0
#
# On failure (missing DB, failed dump, failed integrity check):
#   - Prints an error message to stderr
#   - Exits non-zero; does NOT write .last_success

set -eu

# Trap EXIT to guarantee temp file cleanup even on unexpected exits or signals
_TMPFILE=""
_cleanup() {
    if [ -n "$_TMPFILE" ]; then
        rm -f "$_TMPFILE"
    fi
}
trap '_cleanup' EXIT

DB_PATH="${1:-}"
BACKUP_DIR="${2:-}"

if [ -z "$DB_PATH" ] || [ -z "$BACKUP_DIR" ]; then
    echo "[backup] ERROR: usage: backup.sh <db_path> <backup_dir>" >&2
    exit 1
fi

if [ ! -f "$DB_PATH" ]; then
    echo "[backup] ERROR: database not found: $DB_PATH" >&2
    exit 1
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
_TMPFILE="$(mktemp /tmp/backup-XXXXXX.sql.gz)"

# Dump + compress into a temp file so a partial write is never mistaken for valid
if ! sqlite3 "$DB_PATH" '.dump' | gzip > "$_TMPFILE"; then
    echo "[backup] ERROR: dump/compress failed for $DB_PATH" >&2
    exit 1
fi

# Integrity check before promoting to the final location
if ! gzip -t "$_TMPFILE"; then
    echo "[backup] ERROR: integrity check failed — discarding $_TMPFILE" >&2
    exit 1
fi

FINAL="$BACKUP_DIR/worship-${STAMP}.sql.gz"
mv "$_TMPFILE" "$FINAL"
_TMPFILE=""  # file promoted — no cleanup needed

# Record timestamp of last successful backup for healthcheck monitoring
echo "$STAMP" > "$BACKUP_DIR/.last_success"

echo "[backup] OK: $FINAL"

# Optional healthcheck ping — set BACKUP_HEALTHCHECK_URL to a ping-style URL
# (healthchecks.io, UptimeRobot, or any HTTP endpoint).  Failure to ping is
# non-fatal: we log a warning but do not change the exit code.
if [ -n "${BACKUP_HEALTHCHECK_URL:-}" ]; then
    curl -fsS --retry 3 "${BACKUP_HEALTHCHECK_URL}" > /dev/null 2>&1 || \
        echo "[backup] WARNING: healthcheck ping failed for ${BACKUP_HEALTHCHECK_URL}" >&2
fi
