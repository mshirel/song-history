"""Tests for scripts/backup.sh — integrity check and sentinel file (#28)."""

import gzip
import subprocess
from pathlib import Path

import pytest

BACKUP_SCRIPT = Path(__file__).parent.parent / "scripts" / "backup.sh"


def run_backup(
    db_path: Path, backup_dir: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(BACKUP_SCRIPT), str(db_path), str(backup_dir)],
        capture_output=True,
        text=True,
    )


@pytest.mark.slow
class TestBackupIntegrityCheck:
    """backup.sh writes a valid gzip and sentinel file on success.

    Marked ``slow`` because every test in this class spawns a subprocess
    to invoke bash scripts/backup.sh, which involves fork + exec overhead.
    """

    def test_backup_creates_gz_file(self, tmp_path: Path) -> None:
        """A successful backup produces a worship-*.sql.gz file."""
        db_path = tmp_path / "worship.db"
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        # Create a minimal SQLite DB
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        result = run_backup(db_path, backup_dir)
        assert result.returncode == 0, result.stderr
        gz_files = list(backup_dir.glob("worship-*.sql.gz"))
        assert len(gz_files) == 1

    def test_backup_gz_is_valid_gzip(self, tmp_path: Path) -> None:
        """The produced .sql.gz passes gzip -t integrity check."""
        db_path = tmp_path / "worship.db"
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        run_backup(db_path, backup_dir)
        gz_file = next(backup_dir.glob("worship-*.sql.gz"))

        check = subprocess.run(["gzip", "-t", str(gz_file)], capture_output=True)
        assert check.returncode == 0

    def test_backup_writes_last_success_sentinel(self, tmp_path: Path) -> None:
        """A successful backup writes .last_success into the backup dir."""
        db_path = tmp_path / "worship.db"
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        run_backup(db_path, backup_dir)
        sentinel = backup_dir / ".last_success"
        assert sentinel.exists()
        assert len(sentinel.read_text().strip()) > 0

    def test_backup_fails_when_db_missing(self, tmp_path: Path) -> None:
        """backup.sh exits non-zero when the database file does not exist."""
        db_path = tmp_path / "nonexistent.db"
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        result = run_backup(db_path, backup_dir)
        assert result.returncode != 0

    def test_backup_does_not_write_sentinel_on_failure(self, tmp_path: Path) -> None:
        """When backup fails, .last_success is not written."""
        db_path = tmp_path / "nonexistent.db"
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        run_backup(db_path, backup_dir)
        assert not (backup_dir / ".last_success").exists()


@pytest.mark.slow
class TestBackupTempCleanup:
    """backup.sh must clean up temp files on exit, even on failure — closes #63."""

    def test_backup_sh_contains_exit_trap(self) -> None:
        """backup.sh must declare a trap on EXIT to clean up temp files."""
        content = BACKUP_SCRIPT.read_text()
        assert "trap" in content, "backup.sh must contain a trap statement"
        assert "EXIT" in content, "backup.sh must trap EXIT for cleanup"

    def test_backup_cleans_up_temp_files_on_success(self, tmp_path: Path) -> None:
        """After a successful backup, no leftover temp files remain in /tmp."""
        import sqlite3
        db_path = tmp_path / "worship.db"
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        # Count /tmp/backup-* files before and after
        before = set(Path("/tmp").glob("backup-*.sql.gz"))
        result = run_backup(db_path, backup_dir)
        after = set(Path("/tmp").glob("backup-*.sql.gz"))
        assert result.returncode == 0, result.stderr
        leftover = after - before
        assert len(leftover) == 0, f"Temp files not cleaned up: {leftover}"

    def test_backup_cleans_up_temp_files_on_failure(self, tmp_path: Path) -> None:
        """After a failed backup, no leftover temp files remain in /tmp."""
        db_path = tmp_path / "nonexistent.db"
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        before = set(Path("/tmp").glob("backup-*.sql.gz"))
        result = run_backup(db_path, backup_dir)
        after = set(Path("/tmp").glob("backup-*.sql.gz"))
        assert result.returncode != 0
        leftover = after - before
        assert len(leftover) == 0, f"Temp files not cleaned up on failure: {leftover}"


def _run_backup_with_env(
    db_path: Path,
    backup_dir: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run backup.sh with optional extra environment variables."""
    import os
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(BACKUP_SCRIPT), str(db_path), str(backup_dir)],
        capture_output=True,
        text=True,
        env=env,
    )


def _make_db(tmp_path: Path) -> Path:
    """Create a minimal SQLite DB for testing."""
    import sqlite3
    db_path = tmp_path / "worship.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    return db_path


@pytest.mark.slow
class TestBackupHealthcheckPing:
    """backup.sh must send a healthcheck ping on success — closes #136."""

    def test_ping_sent_on_success_when_url_configured(self, tmp_path: Path) -> None:
        """When BACKUP_HEALTHCHECK_URL is set, backup.sh must curl it after a successful backup."""
        import http.server
        import threading

        # Start a minimal HTTP server to capture the ping
        ping_received: list[bool] = []

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                ping_received.append(True)
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args: object) -> None:
                pass  # silence server logs during tests

        server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        port = server.server_address[1]
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()

        db_path = _make_db(tmp_path)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        result = _run_backup_with_env(
            db_path,
            backup_dir,
            extra_env={"BACKUP_HEALTHCHECK_URL": f"http://127.0.0.1:{port}/ping"},
        )
        t.join(timeout=3)
        server.server_close()

        assert result.returncode == 0, result.stderr
        assert ping_received, (
            "backup.sh did not send a GET request to BACKUP_HEALTHCHECK_URL on success"
        )

    def test_no_ping_when_url_not_set(self, tmp_path: Path) -> None:
        """When BACKUP_HEALTHCHECK_URL is unset, backup.sh must not curl anything."""
        import http.server
        import threading

        # Start a server to detect any unexpected pings
        ping_received: list[bool] = []

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                ping_received.append(True)
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args: object) -> None:
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()

        db_path = _make_db(tmp_path)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        import os
        env = os.environ.copy()
        env.pop("BACKUP_HEALTHCHECK_URL", None)  # ensure not set
        result = subprocess.run(
            ["bash", str(BACKUP_SCRIPT), str(db_path), str(backup_dir)],
            capture_output=True,
            text=True,
            env=env,
        )
        # Give a moment for any stray requests, then shut down
        t.join(timeout=0.5)
        server.server_close()

        assert result.returncode == 0, result.stderr
        assert not ping_received, (
            "backup.sh must not send any ping when BACKUP_HEALTHCHECK_URL is unset"
        )

    def test_backup_script_contains_healthcheck_url_logic(self) -> None:
        """backup.sh source must include BACKUP_HEALTHCHECK_URL env-var guard."""
        content = BACKUP_SCRIPT.read_text()
        assert "BACKUP_HEALTHCHECK_URL" in content, (
            "backup.sh must support the BACKUP_HEALTHCHECK_URL env var"
        )

    def test_failure_logs_error_to_stderr(self, tmp_path: Path) -> None:
        """When backup fails, an ERROR line must be printed to stderr."""
        db_path = tmp_path / "nonexistent.db"
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        result = run_backup(db_path, backup_dir)
        assert result.returncode != 0
        assert "ERROR" in result.stderr, (
            f"backup.sh must log ERROR to stderr on failure, got: {result.stderr!r}"
        )
