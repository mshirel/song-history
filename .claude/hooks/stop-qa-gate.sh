#!/usr/bin/env bash
# .claude/hooks/stop-qa-gate.sh
#
# Stop Hook — mandatory QA gate before task completion.
#
# Enforces:
#   1. pytest        — full test suite
#   2. ruff          — lint
#   3. mypy          — type checking
#
# Exit 0  → gate passes, Claude may finish.
# Exit 2  → gate fails, Claude is blocked and must address failures.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

PASS=0
FAIL=0

run_check() {
    local label="$1"
    shift
    echo "── $label"
    if "$@" 2>&1; then
        echo "   ✓ passed"
    else
        echo "   ✗ FAILED"
        FAIL=$(( FAIL + 1 ))
        return 0  # keep running remaining checks
    fi
    PASS=$(( PASS + 1 ))
}

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   QA Gate — pre-stop validation      ║"
echo "╚══════════════════════════════════════╝"
echo ""

run_check "pytest"          python3 -m pytest -q --tb=short --no-header
run_check "ruff check src/" python3 -m ruff check src/
run_check "mypy src/"       python3 -m mypy src/

echo ""
echo "── Results: ${PASS} passed, ${FAIL} failed"

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "QA gate BLOCKED — fix the failures above before finishing."
    echo "If failures are pre-existing defects unrelated to this task,"
    echo "open a GitHub issue and document why completion is still safe."
    echo ""
    exit 2
fi

echo ""
echo "QA gate PASSED — task may complete."
echo ""
exit 0
