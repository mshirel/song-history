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
#   - Sends a Pushover notification if PUSHOVER_APP_TOKEN + PUSHOVER_USER_KEY are set
#   - Exits non-zero; does NOT write .last_success
#
# Pushover alerting (optional):
#   Set PUSHOVER_APP_TOKEN and PUSHOVER_USER_KEY in the environment.
#   PUSHOVER_API_URL overrides the endpoint (used in tests).

set -eu

# Trap EXIT to guarantee temp file cleanup and Pushover failure notifications.
_TMPFILE=""
_cleanup() {
    _rc=$?
    if [ -n "$_TMPFILE" ]; then
        rm -f "$_TMPFILE"
    fi
    if [ "${_rc}" -ne 0 ] \
       && [ -n "${PUSHOVER_APP_TOKEN:-}" ] \
       && [ -n "${PUSHOVER_USER_KEY:-}" ]; then
        _api_url="${PUSHOVER_API_URL:-https://api.pushover.net/1/messages.json}"
        _host="$(hostname 2>/dev/null || echo unknown)"
        curl -fsS --retry 3 \
            --form-string "token=${PUSHOVER_APP_TOKEN}" \
            --form-string "user=${PUSHOVER_USER_KEY}" \
            --form-string "title=Song History: Backup Failed" \
            --form-string "message=Backup failed on ${_host} for ${DB_PATH}" \
            "${_api_url}" > /dev/null 2>&1 || \
            echo "[backup] WARNING: Pushover notification failed" >&2
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

# Record timestamp of last successful backup
echo "$STAMP" > "$BACKUP_DIR/.last_success"

echo "[backup] OK: $FINAL"
