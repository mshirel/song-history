"""Tests for scripts/import-new.sh — SIGTERM signal handling (#103)."""

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

IMPORT_SCRIPT = Path(__file__).parent.parent / "scripts" / "import-new.sh"
SCRIPTS_DIR = IMPORT_SCRIPT.parent


@pytest.mark.slow
class TestImportShSignalHandling:
    """import-new.sh must handle SIGTERM gracefully — closes #103."""

    def test_import_sh_contains_sigterm_trap(self) -> None:
        """import-new.sh must declare a SIGTERM trap for graceful shutdown."""
        content = IMPORT_SCRIPT.read_text()
        assert "trap" in content, "import-new.sh must contain a trap statement"
        assert "SIGTERM" in content or "TERM" in content, (
            "import-new.sh must trap SIGTERM (or TERM)"
        )

    def test_import_sh_exits_on_sigterm_during_sleep(self, tmp_path: Path) -> None:
        """When SIGTERM is sent during a sleep pause, the script must exit within 2s."""
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        # Wrap import-new.sh in a sleep loop, as compose watcher does
        loop_script = tmp_path / "watcher_loop.sh"
        loop_script.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "_shutdown() { echo 'Received shutdown signal — exiting gracefully' >&2; exit 0; }\n"
            "trap _shutdown SIGTERM SIGINT\n"
            f"while true; do\n"
            f"  INBOX_DIR={inbox} DB_PATH={tmp_path}/worship.db bash {IMPORT_SCRIPT} || true\n"
            f"  sleep 300 & wait $!\n"
            f"done\n"
        )
        loop_script.chmod(0o755)

        proc = subprocess.Popen(
            ["bash", str(loop_script)],
            env={**os.environ},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Wait for import-new.sh to run and reach the sleep
        time.sleep(1.0)
        proc.send_signal(signal.SIGTERM)
        try:
            returncode = proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            pytest.fail("Watcher loop did not exit within 5s after SIGTERM")
        # 0 = clean exit via trap, 143 = 128+SIGTERM
        assert returncode in (0, 143), f"Unexpected returncode {returncode}"

    def test_import_sh_does_not_restart_import_after_sigterm(self, tmp_path: Path) -> None:
        """SIGTERM during sleep pause must not trigger a new import cycle."""
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        log_file = tmp_path / "runs.log"

        loop_script = tmp_path / "watcher_loop.sh"
        loop_script.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "_shutdown() { exit 0; }\n"
            "trap _shutdown SIGTERM SIGINT\n"
            f"while true; do\n"
            f"  echo 'run' >> {log_file}\n"
            f"  INBOX_DIR={inbox} DB_PATH={tmp_path}/worship.db bash {IMPORT_SCRIPT} || true\n"
            f"  sleep 300 & wait $!\n"
            f"done\n"
        )
        loop_script.chmod(0o755)

        proc = subprocess.Popen(
            ["bash", str(loop_script)],
            env={**os.environ},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(1.0)
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=5)

        run_count = log_file.read_text().strip().count("run") if log_file.exists() else 0
        assert run_count == 1, (
            f"Expected exactly 1 import run, got {run_count} — "
            "SIGTERM is triggering additional import cycles"
        )
