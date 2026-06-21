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
# .env holds all deployment secrets (Cloudflare/tunnel tokens, CSRF, upload
# password) — it must be owner-only (600), never world-readable (#446).
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env}"

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

# ---------------------------------------------------------------------------
# Check: .env permissions
# .env contains every deployment secret; it must be 600 so other local users
# (and non-root container breakouts) can't read it (#446).
# ---------------------------------------------------------------------------
if [ -f "$ENV_FILE" ]; then
    ENV_PERMS="$(stat -c "%a" "$ENV_FILE")"
    if [ "$ENV_PERMS" != "600" ]; then
        echo "ERROR: .env has permissions $ENV_PERMS — must be 600 (it holds secrets)" >&2
        echo "Fix with: chmod 600 $ENV_FILE" >&2
        exit 1
    fi
fi

echo "[init] Pre-flight checks passed."
exit 0
