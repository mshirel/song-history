"""Tests for scripts/backup.sh — integrity check and sentinel file (#28)."""

import gzip
import subprocess
from pathlib import Path

BACKUP_SCRIPT = Path(__file__).parent.parent / "scripts" / "backup.sh"


def run_backup(
    db_path: Path, backup_dir: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(BACKUP_SCRIPT), str(db_path), str(backup_dir)],
        capture_output=True,
        text=True,
    )


class TestBackupIntegrityCheck:
    """backup.sh writes a valid gzip and sentinel file on success."""

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
