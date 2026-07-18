"""Integration tests for the shared service import transaction."""

import threading

import pytest

from worship_catalog.db import Database
from worship_catalog.extractor import ExtractionResult, SongOccurrence
from worship_catalog.import_service import run_import


class _ServiceSelectBarrierCursor:
    """Align unprotected service reads without blocking a write transaction."""

    def __init__(self, cursor, barrier):
        self._cursor = cursor
        self._barrier = barrier

    def execute(self, sql, parameters=()):
        result = self._cursor.execute(sql, parameters)
        normalized_sql = " ".join(sql.split())
        if (
            normalized_sql.startswith("SELECT id FROM services WHERE service_date")
            and not self._cursor.connection.in_transaction
        ):
            self._barrier.wait(timeout=5)
        return result

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _ServiceSelectBarrierConnection:
    def __init__(self, connection, barrier):
        self._connection = connection
        self._barrier = barrier

    def cursor(self):
        return _ServiceSelectBarrierCursor(self._connection.cursor(), self._barrier)

    def __getattr__(self, name):
        return getattr(self._connection, name)


@pytest.mark.integration
def test_concurrent_insert_or_update_service_returns_one_id(tmp_path):
    """The service API resolves a concurrent unique conflict itself."""
    db_path = tmp_path / "service_upsert.db"
    init = Database(db_path)
    init.connect()
    init.init_schema()
    init.close()

    service_select_barrier = threading.Barrier(2)
    connection_lock = threading.Lock()
    errors: list[Exception] = []
    service_ids: list[int] = []

    def worker(source: str) -> None:
        with connection_lock:
            db = Database(db_path)
            db.connect()
            db.conn.execute("PRAGMA busy_timeout=5000")
        db.conn = _ServiceSelectBarrierConnection(db.conn, service_select_barrier)
        try:
            service_ids.append(
                db.insert_or_update_service(
                    "2026-03-01",
                    "Morning Worship",
                    f"{source}.pptx",
                    f"hash-{source}",
                )
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            db.close()

    threads = [
        threading.Thread(target=worker, args=("first",)),
        threading.Thread(target=worker, args=("second",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in threads)
    assert not errors, f"Concurrent insert_or_update_service raised: {errors!r}"
    assert len(service_ids) == 2
    assert len(set(service_ids)) == 1

    check = Database(db_path)
    check.connect()
    try:
        assert check.conn.execute("SELECT COUNT(*) FROM services").fetchone()[0] == 1
        row = check.conn.execute("SELECT source_file, source_hash FROM services").fetchone()
        assert (row["source_file"], row["source_hash"]) in {
            ("first.pptx", "hash-first"),
            ("second.pptx", "hash-second"),
        }
    finally:
        check.close()


@pytest.mark.integration
def test_concurrent_same_service_imports_replace_atomically(tmp_path, monkeypatch):
    """Two imports for one slot both succeed and leave one complete service."""
    db_path = tmp_path / "same_service.db"
    init = Database(db_path)
    init.connect()
    init.init_schema()
    init.close()

    extraction_barrier = threading.Barrier(2)
    service_select_barrier = threading.Barrier(2)
    connection_lock = threading.Lock()
    errors: list[Exception] = []
    imported: list[int] = []

    def fake_extract_songs(path, **_kwargs):
        extraction_barrier.wait(timeout=5)
        return ExtractionResult(
            filename=path.name,
            file_hash=f"hash-{path.stem}",
            service_date="2026-03-01",
            service_name="Morning Worship",
            song_leader=path.stem,
            preacher=None,
            sermon_title=None,
            songs=[
                SongOccurrence(
                    ordinal=1,
                    canonical_title="amazing grace",
                    display_title="Amazing Grace",
                )
            ],
        )

    monkeypatch.setattr("worship_catalog.extractor.extract_songs", fake_extract_songs)

    def worker(filename: str) -> None:
        with connection_lock:
            db = Database(db_path)
            db.connect()
            db.conn.execute("PRAGMA busy_timeout=5000")
        db.conn = _ServiceSelectBarrierConnection(db.conn, service_select_barrier)
        try:
            result = run_import(db, tmp_path / filename)
            imported.append(result.songs_imported)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            db.close()

    threads = [
        threading.Thread(target=worker, args=("first.pptx",)),
        threading.Thread(target=worker, args=("second.pptx",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in threads)
    assert not errors, f"Concurrent same-service import raised: {errors!r}"
    assert imported == [1, 1]

    check = Database(db_path)
    check.connect()
    try:
        assert check.conn.execute("SELECT COUNT(*) FROM services").fetchone()[0] == 1
        assert check.conn.execute("SELECT COUNT(*) FROM service_songs").fetchone()[0] == 1
        assert check.conn.execute("SELECT COUNT(*) FROM copy_events").fetchone()[0] == 2
        row = check.conn.execute("SELECT source_hash, song_leader FROM services").fetchone()
        assert (row["source_hash"], row["song_leader"]) in {
            ("hash-first", "first"),
            ("hash-second", "second"),
        }
    finally:
        check.close()
