#!/usr/bin/env bash
# import-new.sh — Watch an inbox folder and import new PPTX files into the worship DB.
#
# Usage:
#   INBOX_DIR=/path/to/inbox ./scripts/import-new.sh
#   ./scripts/import-new.sh          # uses defaults below
#
# Cron example (run every 5 minutes, log to file):
#   */5 * * * * LOG_FILE=/var/log/worship-import.log \
#               INBOX_DIR=/data/inbox \
#               DB_PATH=/data/worship.db \
#               /app/scripts/import-new.sh
#
# Files that import successfully are moved to $INBOX_DIR/archive/.
# Files that fail are retried up to $MAX_FAILURES times; on the Nth failure
# they are moved to $INBOX_DIR/quarantine/.
# Failure counts are tracked in $INBOX_DIR/.import_failures.json.

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration — override any of these via environment variables
# ---------------------------------------------------------------------------
INBOX_DIR="${INBOX_DIR:-./inbox}"
DB_PATH="${DB_PATH:-./data/worship.db}"
MAX_FAILURES="${MAX_FAILURES:-3}"
LOG_FILE="${LOG_FILE:-}"   # empty = stdout only

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log() {
    local msg="[$(date '+%Y-%m-%dT%H:%M:%S')] $*"
    echo "$msg"
    if [[ -n "$LOG_FILE" ]]; then
        echo "$msg" >> "$LOG_FILE"
    fi
}

FAILURES_JSON="${INBOX_DIR}/.import_failures.json"

# Resolve path to failure_tracker.py relative to this script — never interpolate
# filenames into Python code strings (fixes CWE-78 shell injection).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FAILURE_TRACKER="${SCRIPT_DIR}/failure_tracker.py"

get_failure_count() {
    python3 "$FAILURE_TRACKER" get "$FAILURES_JSON" "$1"
}

set_failure_count() {
    python3 "$FAILURE_TRACKER" set "$FAILURES_JSON" "$1" "$2"
}

clear_failure_record() {
    python3 "$FAILURE_TRACKER" clear "$FAILURES_JSON" "$1"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
ARCHIVE_DIR="${INBOX_DIR}/archive"
QUARANTINE_DIR="${INBOX_DIR}/quarantine"

mkdir -p "$INBOX_DIR" "$ARCHIVE_DIR" "$QUARANTINE_DIR"

shopt -s nullglob
pptx_files=("${INBOX_DIR}"/*.pptx "${INBOX_DIR}"/*.PPTX)
shopt -u nullglob

if [[ ${#pptx_files[@]} -eq 0 ]]; then
    log "No PPTX files found in ${INBOX_DIR} — nothing to do."
    exit 0
fi

log "Found ${#pptx_files[@]} file(s) in ${INBOX_DIR}."

for filepath in "${pptx_files[@]}"; do
    filename="$(basename "$filepath")"

    # Refuse to process symlinks — prevents symlink-following attacks.
    if [[ -L "$filepath" ]]; then
        log "WARNING: $filepath is a symlink — skipping"
        continue
    fi

    log "Importing: $filename"

    # Capture stdout+stderr so we can log it regardless of success/failure,
    # while still correctly capturing the exit code of worship-catalog itself.
    # The previous pipe pattern (cmd | while ...) swallowed the exit code even
    # with pipefail in some edge cases; this pattern is unambiguous.
    import_output=""
    if import_output=$(worship-catalog import "$filepath" \
        --db "$DB_PATH" \
        --non-interactive 2>&1); then
        # Success — log output then archive
        while IFS= read -r line; do log "  $line"; done <<< "$import_output"
        mv "$filepath" "${ARCHIVE_DIR}/${filename}"
        clear_failure_record "$filename"
        log "  OK — moved to archive."
    else
        # Failure — log output then track and potentially quarantine
        while IFS= read -r line; do log "  $line"; done <<< "$import_output"
        count=$(get_failure_count "$filename")
        count=$((count + 1))

        if [[ $count -ge $MAX_FAILURES ]]; then
            mv "$filepath" "${QUARANTINE_DIR}/${filename}"
            clear_failure_record "$filename"
            log "  FAILED (attempt $count/$MAX_FAILURES) — moved to quarantine."
        else
            set_failure_count "$filename" "$count"
            log "  FAILED (attempt $count/$MAX_FAILURES) — will retry next run."
        fi
    fi
done

log "Done."
