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
class TestBackupPushoverNotification:
    """backup.sh sends a Pushover notification on failure — closes #136."""

    def _make_post_server(self) -> tuple["http.server.HTTPServer", "list[dict[str, str]]"]:
        """Start a local HTTP server that records POST requests."""
        import http.server

        posts_received: list[dict[str, str]] = []

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode()
                posts_received.append({"path": self.path, "body": body})
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"status":1}')

            def log_message(self, *args: object) -> None:
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        return server, posts_received

    def test_pushover_post_sent_on_failure(self, tmp_path: Path) -> None:
        """When both Pushover env vars are set, a POST is sent on backup failure."""
        import threading

        server, posts_received = self._make_post_server()
        port = server.server_address[1]
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()

        db_path = tmp_path / "nonexistent.db"
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        result = _run_backup_with_env(
            db_path,
            backup_dir,
            extra_env={
                "PUSHOVER_APP_TOKEN": "faketoken",
                "PUSHOVER_USER_KEY": "fakeuser",
                "PUSHOVER_API_URL": f"http://127.0.0.1:{port}/messages.json",
            },
        )
        t.join(timeout=3)
        server.server_close()

        assert result.returncode != 0
        assert posts_received, "backup.sh must POST to Pushover when backup fails"
        assert "faketoken" in posts_received[0]["body"]
        assert "fakeuser" in posts_received[0]["body"]

    def test_no_notification_on_success(self, tmp_path: Path) -> None:
        """A successful backup must NOT send a Pushover notification."""
        import threading

        server, posts_received = self._make_post_server()
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()

        db_path = _make_db(tmp_path)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        result = _run_backup_with_env(
            db_path,
            backup_dir,
            extra_env={
                "PUSHOVER_APP_TOKEN": "faketoken",
                "PUSHOVER_USER_KEY": "fakeuser",
            },
        )
        t.join(timeout=0.5)
        server.server_close()

        assert result.returncode == 0, result.stderr
        assert not posts_received, "backup.sh must NOT notify Pushover on success"

    def test_no_notification_when_vars_unset(self, tmp_path: Path) -> None:
        """When Pushover env vars are absent, no HTTP request is made on failure."""
        import os
        import threading

        server, posts_received = self._make_post_server()
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()

        db_path = tmp_path / "nonexistent.db"
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        env = os.environ.copy()
        env.pop("PUSHOVER_APP_TOKEN", None)
        env.pop("PUSHOVER_USER_KEY", None)
        result = subprocess.run(
            ["bash", str(BACKUP_SCRIPT), str(db_path), str(backup_dir)],
            capture_output=True,
            text=True,
            env=env,
        )
        t.join(timeout=0.5)
        server.server_close()

        assert result.returncode != 0
        assert not posts_received, "backup.sh must not notify when Pushover vars are unset"

    def test_only_token_set_does_not_notify(self, tmp_path: Path) -> None:
        """Setting only PUSHOVER_APP_TOKEN without USER_KEY must skip notification."""
        import os
        import threading

        server, posts_received = self._make_post_server()
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()

        db_path = tmp_path / "nonexistent.db"
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        env = os.environ.copy()
        env["PUSHOVER_APP_TOKEN"] = "faketoken"
        env.pop("PUSHOVER_USER_KEY", None)
        result = subprocess.run(
            ["bash", str(BACKUP_SCRIPT), str(db_path), str(backup_dir)],
            capture_output=True,
            text=True,
            env=env,
        )
        t.join(timeout=0.5)
        server.server_close()

        assert result.returncode != 0
        assert not posts_received, "backup.sh must not notify when USER_KEY is missing"

    def test_notification_failure_is_non_fatal(self, tmp_path: Path) -> None:
        """If the Pushover POST fails, backup.sh exits with the backup exit code, not a curl error."""
        db_path = tmp_path / "nonexistent.db"
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        result = _run_backup_with_env(
            db_path,
            backup_dir,
            extra_env={
                "PUSHOVER_APP_TOKEN": "faketoken",
                "PUSHOVER_USER_KEY": "fakeuser",
                "PUSHOVER_API_URL": "http://127.0.0.1:19999/messages.json",
            },
        )
        assert result.returncode != 0  # backup failed, not curl failure

    def test_backup_script_contains_pushover_logic(self) -> None:
        """backup.sh source must reference both PUSHOVER_APP_TOKEN and PUSHOVER_USER_KEY."""
        content = BACKUP_SCRIPT.read_text()
        assert "PUSHOVER_APP_TOKEN" in content
        assert "PUSHOVER_USER_KEY" in content

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
