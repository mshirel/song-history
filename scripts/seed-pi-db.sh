#!/usr/bin/env bash
# seed-pi-db.sh — copy dev worship.db to Pi for first deployment (Option C)
#
# Usage: ./scripts/seed-pi-db.sh <pi-user@pi-host> [source-db-path]
#
# Runs integrity checks on the source DB, copies to the Pi via scp,
# verifies it on the Pi, and prints a go/no-go summary.
set -euo pipefail

PI_HOST="${1:?Usage: seed-pi-db.sh <pi-user@pi-host> [source-db-path]}"
SOURCE_DB="${2:-data/worship.db}"
DEST_PATH="/opt/song-history/data/worship.db"

echo "=== Pre-copy integrity check ==="

if [ ! -f "${SOURCE_DB}" ]; then
    echo "ERROR: source DB not found: ${SOURCE_DB}" >&2
    exit 1
fi

if ! sqlite3 "${SOURCE_DB}" "PRAGMA integrity_check;" 2>/dev/null | grep -q "^ok$"; then
    echo "FAIL: integrity check failed for ${SOURCE_DB}" >&2
    exit 1
fi
echo "Integrity check: ok"

FK_VIOLATIONS="$(sqlite3 "${SOURCE_DB}" "PRAGMA foreign_key_check;" 2>/dev/null || true)"
if [ -n "${FK_VIOLATIONS}" ]; then
    echo "FAIL: FK violations found: ${FK_VIOLATIONS}" >&2
    exit 1
fi
echo "FK check: ok"

SERVICE_COUNT="$(sqlite3 "${SOURCE_DB}" "SELECT COUNT(*) FROM services;" 2>/dev/null || echo 0)"
DATE_RANGE="$(sqlite3 "${SOURCE_DB}" "SELECT MIN(service_date)||' to '||MAX(service_date) FROM services;" 2>/dev/null || echo "unknown")"
echo "Services: ${SERVICE_COUNT} (${DATE_RANGE})"
echo ""

read -rp "Copy this DB to ${PI_HOST}:${DEST_PATH}? [y/N] " confirm
if [[ ! "${confirm}" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

echo "=== Copying ==="
scp "${SOURCE_DB}" "${PI_HOST}:${DEST_PATH}"

echo "=== Post-copy verification ==="
if ssh "${PI_HOST}" "sqlite3 ${DEST_PATH} 'PRAGMA integrity_check;'" 2>/dev/null | grep -q "^ok$"; then
    echo "Pi integrity check: ok"
else
    echo "FAIL: Pi integrity check failed — check ${PI_HOST}:${DEST_PATH}" >&2
    exit 1
fi

echo ""
echo "=== Done ==="
echo "Next steps:"
echo "  ssh ${PI_HOST}"
echo "  cd /opt/song-history && docker compose up -d web"
echo "  curl http://localhost:8000/health"
