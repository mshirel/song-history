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
TMP_FILE="$(mktemp /tmp/backup-XXXXXX.sql.gz)"

# Dump + compress into a temp file so a partial write is never mistaken for valid
if ! sqlite3 "$DB_PATH" '.dump' | gzip > "$TMP_FILE"; then
    echo "[backup] ERROR: dump/compress failed for $DB_PATH" >&2
    rm -f "$TMP_FILE"
    exit 1
fi

# Integrity check before promoting to the final location
if ! gzip -t "$TMP_FILE"; then
    echo "[backup] ERROR: integrity check failed — discarding $TMP_FILE" >&2
    rm -f "$TMP_FILE"
    exit 1
fi

FINAL="$BACKUP_DIR/worship-${STAMP}.sql.gz"
mv "$TMP_FILE" "$FINAL"

# Record timestamp of last successful backup for healthcheck monitoring
echo "$STAMP" > "$BACKUP_DIR/.last_success"

echo "[backup] OK: $FINAL"
