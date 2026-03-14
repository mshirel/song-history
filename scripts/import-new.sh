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

get_failure_count() {
    local filename="$1"
    if [[ ! -f "$FAILURES_JSON" ]]; then
        echo 0
        return
    fi
    python3 -c "
import json, sys
data = json.loads(open('$FAILURES_JSON').read())
print(data.get('$filename', {}).get('count', 0))
"
}

set_failure_count() {
    local filename="$1"
    local count="$2"
    python3 -c "
import json, sys
from datetime import datetime
path = '$FAILURES_JSON'
try:
    data = json.loads(open(path).read())
except (FileNotFoundError, json.JSONDecodeError):
    data = {}
data['$filename'] = {'count': $count, 'last_failure': datetime.now().isoformat(timespec='seconds')}
open(path, 'w').write(json.dumps(data, indent=2))
"
}

clear_failure_record() {
    local filename="$1"
    if [[ ! -f "$FAILURES_JSON" ]]; then
        return
    fi
    python3 -c "
import json
path = '$FAILURES_JSON'
try:
    data = json.loads(open(path).read())
except (FileNotFoundError, json.JSONDecodeError):
    data = {}
data.pop('$filename', None)
open(path, 'w').write(json.dumps(data, indent=2))
"
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
