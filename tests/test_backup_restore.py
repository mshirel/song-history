"""Tests for backup restore procedure (#35)."""
import sqlite3
import subprocess
from pathlib import Path

import pytest

BACKUP_SCRIPT = Path(__file__).parent.parent / "scripts" / "backup.sh"


class TestBackupRestoreProcedure:
    def test_backup_can_be_restored_to_empty_db(self, tmp_path: Path) -> None:
        """A backup created by backup.sh can be fully restored with gunzip | sqlite3."""
        # Set up source DB with known data
        src_db = tmp_path / "worship.db"
        conn = sqlite3.connect(src_db)
        conn.execute("CREATE TABLE songs (id INTEGER PRIMARY KEY, title TEXT)")
        conn.execute("INSERT INTO songs VALUES (1, 'Amazing Grace')")
        conn.commit()
        conn.close()

        # Create backup
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        result = subprocess.run(
            ["bash", str(BACKUP_SCRIPT), str(src_db), str(backup_dir)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

        # Restore to a new DB
        gz_file = next(backup_dir.glob("worship-*.sql.gz"))
        restore_db = tmp_path / "restore.db"
        restore_cmd = f"gunzip -c {gz_file} | sqlite3 {restore_db}"
        r = subprocess.run(restore_cmd, shell=True, capture_output=True, text=True)  # noqa: S602
        assert r.returncode == 0

        # Verify restored data
        conn2 = sqlite3.connect(restore_db)
        rows = conn2.execute("SELECT title FROM songs").fetchall()
        conn2.close()
        assert len(rows) == 1
        assert rows[0][0] == "Amazing Grace"

    def test_restored_db_has_nonzero_song_count_after_schema_restore(self, tmp_path):
        """Restoring a full schema backup produces a working database."""
        from worship_catalog.db import Database
        src_db = tmp_path / "worship.db"
        db = Database(src_db)
        db.connect()
        db.init_schema()
        db.insert_or_get_song("amazing grace", "Amazing Grace")
        db.insert_or_get_song("holy holy holy", "Holy Holy Holy")
        db.close()

        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        subprocess.run(
            ["bash", str(BACKUP_SCRIPT), str(src_db), str(backup_dir)],
            check=True, capture_output=True,
        )

        gz_file = next(backup_dir.glob("worship-*.sql.gz"))
        restore_db = tmp_path / "restore.db"
        subprocess.run(
            f"gunzip -c {gz_file} | sqlite3 {restore_db}",
            shell=True, check=True, capture_output=True,  # noqa: S602
        )

        conn = sqlite3.connect(restore_db)
        count = conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
        conn.close()
        assert count == 2
