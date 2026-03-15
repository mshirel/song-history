#!/bin/sh
# deploy/pi/init.sh — Pi deployment pre-flight checks.
#
# Run this script before `docker compose up -d` to validate the deployment
# environment. Exits non-zero (and prints guidance to stderr) if any check fails.
#
# Usage:
#   ./deploy/pi/init.sh
#   ACME_DIR=/custom/path ./deploy/pi/init.sh   # override acme.json location

set -eu

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# ACME_DIR defaults to the traefik/ subdirectory alongside this script.
# Override via environment variable for testing.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ACME_DIR="${ACME_DIR:-${SCRIPT_DIR}/traefik}"
ACME_FILE="${ACME_DIR}/acme.json"

# ---------------------------------------------------------------------------
# Check: acme.json permissions
# Traefik refuses to start if acme.json is not exactly 600.
# ---------------------------------------------------------------------------
if [ -f "$ACME_FILE" ]; then
    PERMS="$(stat -c "%a" "$ACME_FILE")"
    if [ "$PERMS" != "600" ]; then
        echo "ERROR: acme.json has permissions $PERMS — must be 600" >&2
        echo "Fix with: chmod 600 $ACME_FILE" >&2
        exit 1
    fi
fi

echo "[init] Pre-flight checks passed."
exit 0
