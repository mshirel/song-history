"""SQLite database schema and operations."""

import logging
import sqlite3
import warnings
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from worship_catalog.normalize import normalize_service_date
from worship_catalog.service_slots import classify_service_slot

_log = logging.getLogger("worship_catalog.db")

# Bump this integer whenever the schema changes.  Each new version must have a
# corresponding entry in _MIGRATIONS.  connect() raises SchemaVersionError if the
# on-disk version is *higher* than this value (DB created by a newer release).
_SCHEMA_VERSION: int = 7

# Ordered dict of version → list of SQL statements.  Each migration brings the
# DB from version (N-1) to version N.  Migration 1 is the baseline — it
# creates the import_jobs table that was added in #45.  For a fresh database
# the table already exists (CREATE TABLE IF NOT EXISTS), so the statement is a
# harmless no-op; for a pre-#45 database it fills the gap.
_MIGRATIONS: dict[int, list[str]] = {
    1: [
        """
        CREATE TABLE IF NOT EXISTS import_jobs (
            job_id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            started_at TEXT NOT NULL,
            completed_at TEXT,
            songs_imported INTEGER,
            error_message TEXT
        )
        """,
    ],
    2: [
        # Indexes on song_id for JOIN performance (#308).
        # service_songs.UNIQUE(service_id, ordinal) and
        # copy_events.UNIQUE(service_id, song_id, ...) put service_id first,
        # making song_id-only lookups fall back to full table scans.
        "CREATE INDEX IF NOT EXISTS idx_service_songs_song_id ON service_songs(song_id)",
        "CREATE INDEX IF NOT EXISTS idx_copy_events_song_id ON copy_events(song_id)",
        "CREATE INDEX IF NOT EXISTS idx_services_date ON services(service_date)",
    ],
    3: [
        # Strengthen the services unique constraint from (date, name, hash) to
        # (date, name) so that re-importing a modified file for the same service
        # date+name updates the existing row rather than inserting a duplicate.
        # SQLite doesn't support DROP CONSTRAINT, so we dedup then recreate the table.
        #
        # Guard: if a previous interrupted migration left services_new behind,
        # drop it so this migration can run cleanly from scratch.
        "DROP TABLE IF EXISTS services_new",
        # Step 1 — drop child rows for the loser duplicates (keep highest id per group).
        """
        DELETE FROM copy_events
        WHERE service_id IN (
            SELECT id FROM services
            WHERE id NOT IN (
                SELECT MAX(id) FROM services GROUP BY service_date, service_name
            )
        )
        """,
        """
        DELETE FROM service_songs
        WHERE service_id IN (
            SELECT id FROM services
            WHERE id NOT IN (
                SELECT MAX(id) FROM services GROUP BY service_date, service_name
            )
        )
        """,
        # Step 2 — remove the loser service rows.
        """
        DELETE FROM services
        WHERE id NOT IN (
            SELECT MAX(id) FROM services GROUP BY service_date, service_name
        )
        """,
        # Step 3 — recreate the table with the stronger unique constraint.
        """
        CREATE TABLE services_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_date TEXT NOT NULL,
            service_name TEXT NOT NULL,
            source_file TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            song_leader TEXT,
            preacher TEXT,
            sermon_title TEXT,
            imported_at TEXT NOT NULL,
            UNIQUE(service_date, service_name)
        )
        """,
        """
        INSERT INTO services_new
        SELECT id, service_date, service_name, source_file, source_hash,
               song_leader, preacher, sermon_title, imported_at
        FROM services
        """,
        # Disable FK enforcement so DROP TABLE succeeds even though child
        # tables (service_songs, copy_events) have rows referencing services.
        # _apply_migrations issues COMMIT before any PRAGMA so this PRAGMA
        # takes effect (it is a no-op inside a transaction).
        "PRAGMA foreign_keys=OFF",
        "DROP TABLE services",
        "ALTER TABLE services_new RENAME TO services",
        "PRAGMA foreign_keys=ON",
        "CREATE INDEX IF NOT EXISTS idx_services_date ON services(service_date)",
    ],
    4: [
        # NULL-safe uniqueness for song_editions + copy_events (#420). SQLite's
        # table-level UNIQUE treats each NULL as distinct, so NULL-credit editions
        # and NULL-edition copy_events could duplicate under concurrent imports.
        # De-dupe existing rows (repointing child FKs to the keeper), then add
        # expression UNIQUE indexes that COALESCE NULLs so the constraint actually
        # enforces. With these in place, insert_or_get_* raises IntegrityError on a
        # concurrent NULL duplicate and the existing retry-on-conflict (#400) wins.
        # --- song_editions: map each row to its canonical keeper (min id) ---
        """
        CREATE TEMP TABLE _edition_keep AS
        SELECT e1.id AS dup_id,
               (SELECT MIN(e2.id) FROM song_editions e2
                 WHERE e2.song_id = e1.song_id
                   AND COALESCE(e2.publisher,'') = COALESCE(e1.publisher,'')
                   AND COALESCE(e2.words_by,'')  = COALESCE(e1.words_by,'')
                   AND COALESCE(e2.music_by,'')  = COALESCE(e1.music_by,'')
                   AND COALESCE(e2.arranger,'')  = COALESCE(e1.arranger,'')) AS keep_id
        FROM song_editions e1
        """,
        """
        UPDATE service_songs SET song_edition_id =
            (SELECT keep_id FROM _edition_keep WHERE dup_id = service_songs.song_edition_id)
        WHERE song_edition_id IN (SELECT dup_id FROM _edition_keep WHERE dup_id <> keep_id)
        """,
        """
        UPDATE copy_events SET song_edition_id =
            (SELECT keep_id FROM _edition_keep WHERE dup_id = copy_events.song_edition_id)
        WHERE song_edition_id IN (SELECT dup_id FROM _edition_keep WHERE dup_id <> keep_id)
        """,
        "DELETE FROM song_editions WHERE id IN "
        "(SELECT dup_id FROM _edition_keep WHERE dup_id <> keep_id)",
        "DROP TABLE _edition_keep",
        # --- copy_events: collapse duplicates (after the edition repoint) ---
        """
        DELETE FROM copy_events WHERE id NOT IN (
            SELECT MIN(id) FROM copy_events
            GROUP BY service_id, song_id, COALESCE(song_edition_id, -1), reproduction_type
        )
        """,
        # --- NULL-safe unique indexes (NULLs collapsed via COALESCE) ---
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_song_editions_identity
        ON song_editions(song_id, COALESCE(publisher,''), COALESCE(words_by,''),
                         COALESCE(music_by,''), COALESCE(arranger,''))
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_copy_events_identity
        ON copy_events(service_id, song_id, COALESCE(song_edition_id, -1), reproduction_type)
        """,
    ],
    5: [
        # Add service metadata + song list columns to import_jobs so the web UI
        # can show richer results after a successful import.
        "ALTER TABLE import_jobs ADD COLUMN service_date TEXT",
        "ALTER TABLE import_jobs ADD COLUMN service_name TEXT",
        "ALTER TABLE import_jobs ADD COLUMN song_leader TEXT",
        "ALTER TABLE import_jobs ADD COLUMN preacher TEXT",
        "ALTER TABLE import_jobs ADD COLUMN sermon_title TEXT",
        "ALTER TABLE import_jobs ADD COLUMN songs_json TEXT",
    ],
    6: [
        # Track Sunday service slots (morning/evening) that are intentionally
        # absent, so the missing-services report shows them as deliberate rather
        # than as gaps (#480).
        """
        CREATE TABLE IF NOT EXISTS service_exclusions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_date TEXT NOT NULL,
            service_slot TEXT NOT NULL,
            reason TEXT,
            excluded_at TEXT NOT NULL,
            UNIQUE(service_date, service_slot)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_service_exclusions_date "
        "ON service_exclusions(service_date)",
    ],
    7: [
        # Persist OCR audit details for completed web imports (#537).
        "ALTER TABLE import_jobs ADD COLUMN anomalies_json TEXT",
        "ALTER TABLE import_jobs ADD COLUMN ocr_model TEXT",
        "ALTER TABLE import_jobs ADD COLUMN ocr_calls INTEGER NOT NULL DEFAULT 0",
    ],
}

# Whitelist of column names that update_import_job is allowed to SET.
# Any key not in this set will raise ValueError — prevents SQL injection
# via dynamic field names (issue #100).
_IMPORT_JOB_MUTABLE_FIELDS: frozenset[str] = frozenset(
    {
        "status", "completed_at", "songs_imported", "error_message",
        "service_date", "service_name", "song_leader", "preacher",
        "sermon_title", "songs_json", "anomalies_json", "ocr_model",
        "ocr_calls",
    }
)


_VALID_SORT_DIRS: frozenset[str] = frozenset({"ASC", "DESC"})


def _safe_order_by(col: str, whitelist: frozenset[str]) -> str:
    """Validate *col* against *whitelist* and return it if safe.

    Raises ValueError with "Invalid sort column" if *col* is not in the
    whitelist or is empty/whitespace-only.  This eliminates the need for
    f-string SQL that triggers S608 (SQL injection via format string).
    """
    stripped = col.strip()
    if not stripped or stripped not in whitelist:
        raise ValueError(f"Invalid sort column: {col!r}")
    return stripped


def _safe_sort_dir(direction: str) -> str:
    """Validate sort direction to prevent SQL injection (#316)."""
    upper = direction.strip().upper()
    if upper not in _VALID_SORT_DIRS:
        raise ValueError(f"Invalid sort direction: {direction!r}")
    return upper


def _escape_like(value: str) -> str:
    """Escape LIKE special characters (%, _) in user input (#319)."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class SchemaVersionError(RuntimeError):
    """Raised when the database schema version is incompatible with this code."""


class Database:
    """SQLite database interface for worship catalog.

    **Thread safety:** This class is NOT thread-safe.  Each thread must use
    its own ``Database`` instance.  The ``_in_transaction`` flag and the
    underlying ``sqlite3.Connection`` are not protected by a lock.  In the
    web app, ``get_db()`` creates a new instance per request; background
    import threads call ``_get_db()`` for their own instance (#309).
    """

    def __init__(self, db_path: Path | str = "data/worship.db"):
        """Initialize database connection."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn: sqlite3.Connection | None = None
        self._in_transaction: bool = False

    def __enter__(self) -> "Database":
        """Connect and return self for use as a context manager."""
        self.connect()
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Close the connection on context manager exit."""
        self.close()

    def connect(self) -> sqlite3.Connection:
        """Connect to database.

        Raises SchemaVersionError if the on-disk schema version is newer than
        the version this code supports (i.e. DB created by a newer release).
        """
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA user_version")
        on_disk_version: int = cursor.fetchone()[0]
        if on_disk_version > _SCHEMA_VERSION:
            self.conn.close()
            self.conn = None
            raise SchemaVersionError(
                f"Database schema version {on_disk_version} is newer than this "
                f"version of worship-catalog supports (max {_SCHEMA_VERSION}). "
                "Upgrade the application or restore an older database."
            )
        return self.conn

    @property
    def _conn(self) -> sqlite3.Connection:
        """Return the open connection, asserting it is not None."""
        assert self.conn is not None, "Database not connected — call connect() first"
        return self.conn

    def cursor(self) -> sqlite3.Cursor:
        """Return a cursor for the open connection."""
        return self._conn.cursor()

    def close(self) -> None:
        """Close database connection and null self.conn."""
        if self.conn:
            self.conn.close()
            self.conn = None

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Generator[None, None, None]:
        """Context manager that wraps multiple DB calls in a single transaction.

        Set ``immediate`` when a transaction must read before writing. SQLite
        then reserves the single-writer slot before the first read, preventing
        another writer from invalidating that read snapshot.

        On success: commits once when the block exits.
        On exception: rolls back all changes and re-raises.
        """
        self._in_transaction = True
        try:
            if immediate:
                self._conn.execute("BEGIN IMMEDIATE")
            yield
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            self._in_transaction = False

    def _maybe_commit(self) -> None:
        """Commit only when not inside an explicit transaction() block."""
        if not self._in_transaction:
            self._conn.commit()

    @contextmanager
    def _read_snapshot(self) -> Generator[None, None, None]:
        """Run a group of read queries inside one transaction so they share a
        single, consistent SQLite snapshot (#415).

        Pagination issues a COUNT then a SELECT; without a shared snapshot a
        concurrent writer committing between them yields a total that disagrees
        with the returned rows. A DEFERRED read transaction freezes the snapshot
        at the first read; WAL still allows concurrent writers. No-ops (and does
        not roll back) if a transaction is already active, to avoid disturbing an
        enclosing transaction().
        """
        if self._conn.in_transaction:
            yield
            return
        self._conn.execute("BEGIN")
        try:
            yield
        finally:
            # Read-only: rollback simply releases the snapshot/read lock.
            self._conn.rollback()

    def init_schema(self) -> None:
        """Create database schema and apply any pending migrations.

        For a fresh (empty) database every table is created via
        ``CREATE TABLE IF NOT EXISTS`` and all migrations are recorded.
        For an existing database only the missing migrations are executed,
        bringing the schema up to ``_SCHEMA_VERSION``.
        """
        if not self.conn:
            self.connect()

        cursor = self._conn.cursor()

        # Services table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_date TEXT NOT NULL,
                service_name TEXT NOT NULL,
                song_leader TEXT,
                preacher TEXT,
                sermon_title TEXT,
                source_file TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                UNIQUE(service_date, service_name, source_hash)
            )
            """
        )

        # Songs table (canonical song identity)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_title TEXT UNIQUE NOT NULL,
                display_title TEXT NOT NULL,
                ccli_number TEXT,
                aliases_json TEXT,
                public_domain INTEGER DEFAULT 0
            )
            """
        )

        # Song editions table (specific versions/publishers)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS song_editions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                song_id INTEGER NOT NULL,
                publisher TEXT,
                words_by TEXT,
                music_by TEXT,
                arranger TEXT,
                other_credits TEXT,
                copyright_notice TEXT,
                FOREIGN KEY(song_id) REFERENCES songs(id),
                UNIQUE(song_id, publisher, words_by, music_by, arranger)
            )
            """
        )

        # Service songs join table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS service_songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id INTEGER NOT NULL,
                song_id INTEGER NOT NULL,
                song_edition_id INTEGER,
                ordinal INTEGER NOT NULL,
                occurrences INTEGER,
                first_slide_index INTEGER,
                last_slide_index INTEGER,
                FOREIGN KEY(service_id) REFERENCES services(id),
                FOREIGN KEY(song_id) REFERENCES songs(id),
                FOREIGN KEY(song_edition_id) REFERENCES song_editions(id),
                UNIQUE(service_id, ordinal)
            )
            """
        )

        # Copy events table (what to report to CCLI)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS copy_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id INTEGER NOT NULL,
                song_id INTEGER NOT NULL,
                song_edition_id INTEGER,
                reproduction_type TEXT NOT NULL,
                count INTEGER DEFAULT 1,
                reportable INTEGER DEFAULT 1,
                FOREIGN KEY(service_id) REFERENCES services(id),
                FOREIGN KEY(song_id) REFERENCES songs(id),
                FOREIGN KEY(song_edition_id) REFERENCES song_editions(id),
                UNIQUE(service_id, song_id, song_edition_id, reproduction_type)
            )
            """
        )

        # Import jobs table — tracks background PPTX import jobs submitted via
        # the web upload endpoint (#45).
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS import_jobs (
                job_id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                started_at TEXT NOT NULL,
                completed_at TEXT,
                songs_imported INTEGER,
                error_message TEXT
            )
            """
        )

        # Service exclusions table — Sunday slots intentionally left absent so the
        # missing-services report can distinguish deliberate gaps (#480).
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS service_exclusions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_date TEXT NOT NULL,
                service_slot TEXT NOT NULL,
                reason TEXT,
                excluded_at TEXT NOT NULL,
                UNIQUE(service_date, service_slot)
            )
            """
        )

        # --- Migration tracking & execution ---
        self._apply_migrations()

        self._conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        self._maybe_commit()

    def _apply_migrations(self) -> None:
        """Create schema_migrations table and run any pending migrations."""
        cursor = self._conn.cursor()

        # Ensure the migrations-tracking table exists.
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )

        # Determine which migrations have already been applied.
        cursor.execute("SELECT version FROM schema_migrations")
        applied: set[int] = {row[0] for row in cursor.fetchall()}

        now = datetime.now(tz=timezone.utc).isoformat()

        for version in sorted(_MIGRATIONS):
            if version in applied:
                continue
            for stmt in _MIGRATIONS[version]:
                # PRAGMA foreign_keys is a no-op inside a transaction (SQLite
                # rule).  Commit any pending implicit DML transaction first so
                # the PRAGMA takes effect immediately.
                if stmt.strip().upper().startswith("PRAGMA"):
                    self._conn.commit()
                cursor.execute(stmt)
            cursor.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, now),
            )
            _log.info("Applied schema migration %d", version)

    # --- Songs ---

    def insert_or_get_song(
        self, canonical_title: str, display_title: str
    ) -> int:
        """Insert or get song by canonical title. Returns song_id."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            INSERT INTO songs (canonical_title, display_title)
            VALUES (?, ?)
            ON CONFLICT(canonical_title) DO UPDATE SET id = songs.id
            RETURNING id
            """,
            (canonical_title, display_title),
        )
        row = cursor.fetchone()
        assert row is not None
        self._maybe_commit()
        return int(row[0])

    def insert_or_get_song_edition(
        self,
        song_id: int,
        publisher: str | None = None,
        words_by: str | None = None,
        music_by: str | None = None,
        arranger: str | None = None,
        copyright_notice: str | None = None,
    ) -> int:
        """Insert or get song edition. Returns edition_id."""
        cursor = self._conn.cursor()
        # The identity constraint is an expression index over COALESCE values,
        # so omit a column conflict target and let SQLite match that index.
        cursor.execute(
            """
            INSERT INTO song_editions
            (song_id, publisher, words_by, music_by, arranger, copyright_notice)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT DO UPDATE SET id = song_editions.id
            RETURNING id
            """,
            (song_id, publisher, words_by, music_by, arranger, copyright_notice),
        )
        row = cursor.fetchone()
        assert row is not None
        self._maybe_commit()
        return int(row[0])

    # --- Services ---

    def insert_or_update_service(
        self,
        service_date: str,
        service_name: str,
        source_file: str,
        source_hash: str,
        song_leader: str | None = None,
        preacher: str | None = None,
        sermon_title: str | None = None,
    ) -> int:
        """Insert or update service. Returns service_id.

        ``service_date`` is canonicalized to ISO ``YYYY-MM-DD`` at this write
        boundary (#483) so non-ISO input (e.g. US ``05-31-2026``) can never be
        stored — un-normalized dates sort outside ISO ranges and silently vanish
        from every date-range report. ``normalize_service_dates()`` remains for
        cleaning up legacy rows written before this guard existed.
        """
        service_date = normalize_service_date(service_date) or service_date
        cursor = self._conn.cursor()
        imported_at = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            """
            INSERT INTO services
            (service_date, service_name, source_file, source_hash,
             song_leader, preacher, sermon_title, imported_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(service_date, service_name) DO UPDATE SET
                source_file = excluded.source_file,
                source_hash = excluded.source_hash,
                song_leader = excluded.song_leader,
                preacher = excluded.preacher,
                sermon_title = excluded.sermon_title,
                imported_at = excluded.imported_at
            RETURNING id
            """,
            (
                service_date,
                service_name,
                source_file,
                source_hash,
                song_leader,
                preacher,
                sermon_title,
                imported_at,
            ),
        )
        row = cursor.fetchone()
        assert row is not None
        service_id = int(row[0])

        # A real service now exists for this Sunday slot, so any prior
        # "intentionally excluded" marker is obsolete — clear it so a real
        # import cleanly supersedes a manual exclude and the marker can't
        # resurface if the service is later deleted (#483).
        slot = classify_service_slot(service_name)
        if slot is not None:
            cursor.execute(
                "DELETE FROM service_exclusions WHERE service_date = ? AND service_slot = ?",
                (service_date, slot),  # already normalized to ISO above
            )

        self._maybe_commit()
        return service_id

    # --- Service Songs ---

    def insert_service_song(
        self,
        service_id: int,
        song_id: int,
        ordinal: int,
        song_edition_id: int | None = None,
        first_slide_index: int | None = None,
        last_slide_index: int | None = None,
        occurrences: int = 1,
    ) -> int:
        """Insert service song. Returns service_song_id."""
        cursor = self._conn.cursor()

        cursor.execute(
            """
            INSERT INTO service_songs
            (service_id, song_id, song_edition_id, ordinal,
             first_slide_index, last_slide_index, occurrences)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                service_id,
                song_id,
                song_edition_id,
                ordinal,
                first_slide_index,
                last_slide_index,
                occurrences,
            ),
        )
        self._maybe_commit()
        return cursor.lastrowid

    # --- Copy Events ---

    def insert_copy_event(
        self,
        service_id: int,
        song_id: int,
        reproduction_type: str,
        count: int = 1,
        reportable: bool = True,
        song_edition_id: int | None = None,
    ) -> int:
        """Insert copy event. Returns event_id.

        .. deprecated::
            Use :meth:`insert_or_get_copy_event` instead, which is idempotent
            and safe for duplicate inserts (issue #56).
        """
        warnings.warn(
            "insert_copy_event() is deprecated; use insert_or_get_copy_event() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        cursor = self._conn.cursor()

        cursor.execute(
            """
            INSERT INTO copy_events
            (service_id, song_id, song_edition_id, reproduction_type, count, reportable)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (service_id, song_id, song_edition_id, reproduction_type, count, int(reportable)),
        )
        self._maybe_commit()
        return cursor.lastrowid

    def insert_or_get_copy_event(
        self,
        service_id: int,
        song_id: int,
        reproduction_type: str,
        count: int = 1,
        reportable: bool = True,
        song_edition_id: int | None = None,
    ) -> int:
        """Insert or get copy event. Returns event_id."""
        cursor = self._conn.cursor()

        # Try to get existing - handle NULL comparisons explicitly
        select_sql = """
            SELECT id FROM copy_events
            WHERE service_id = ? AND song_id = ? AND reproduction_type = ?
            AND (song_edition_id = ? OR (song_edition_id IS NULL AND ? IS NULL))
            """
        select_params = (
            service_id, song_id, reproduction_type, song_edition_id, song_edition_id,
        )
        cursor.execute(select_sql, select_params)
        row = cursor.fetchone()
        if row:
            return row[0]

        # Insert new — retry-safe under concurrent writers when song_edition_id
        # is non-NULL (#400).  When song_edition_id is NULL, SQLite's UNIQUE index
        # treats each NULL as distinct, so no IntegrityError fires and concurrent
        # duplicates remain possible — tracked in #420.
        try:
            cursor.execute(
                """
                INSERT INTO copy_events
                (service_id, song_id, song_edition_id, reproduction_type, count, reportable)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (service_id, song_id, song_edition_id, reproduction_type, count, int(reportable)),
            )
            self._maybe_commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            if not self._in_transaction:
                self._conn.rollback()
            cursor.execute(select_sql, select_params)
            row = cursor.fetchone()
            if row:
                return row[0]
            raise

    # --- Queries ---

    def query_services(
        self, start_date: str, end_date: str, song_leader: str | None = None
    ) -> list[dict]:
        """Query services by date range, with optional case-insensitive song leader filter."""
        cursor = self._conn.cursor()
        _svc_cols = (
            "id, service_date, service_name, song_leader, preacher,"
            " sermon_title, source_hash, imported_at"
        )
        if song_leader:
            cursor.execute(
                f"""
                SELECT {_svc_cols} FROM services
                WHERE service_date >= ? AND service_date <= ?
                  AND LOWER(song_leader) LIKE LOWER(?) ESCAPE '\\'
                ORDER BY service_date
                """,
                (start_date, end_date, f"%{_escape_like(song_leader)}%"),
            )
        else:
            cursor.execute(
                f"""
                SELECT {_svc_cols} FROM services
                WHERE service_date >= ? AND service_date <= ?
                ORDER BY service_date
                """,
                (start_date, end_date),
            )
        return [dict(row) for row in cursor.fetchall()]

    def _execute_copy_events_query(
        self, start_date: str, end_date: str, service_ids: list[int] | None = None
    ) -> sqlite3.Cursor:
        """Execute the shared copy-events query and return the cursor (#279)."""
        cursor = self._conn.cursor()
        base = """
            SELECT ce.*, s.canonical_title, s.display_title, sv.service_date, sv.service_name,
                   se.words_by, se.music_by, se.arranger
            FROM copy_events ce
            JOIN services sv ON ce.service_id = sv.id
            JOIN songs s ON ce.song_id = s.id
            LEFT JOIN song_editions se ON ce.song_edition_id = se.id
            WHERE sv.service_date >= ? AND sv.service_date <= ? AND ce.reportable = 1
        """
        params: list[Any] = [start_date, end_date]
        if service_ids is not None:
            placeholders = ",".join("?" * len(service_ids))
            base += f" AND ce.service_id IN ({placeholders})"
            params.extend(service_ids)
        base += " ORDER BY sv.service_date, s.canonical_title"
        cursor.execute(base, params)
        return cursor

    def query_copy_events(
        self, start_date: str, end_date: str, service_ids: list[int] | None = None
    ) -> list[dict]:
        """Query copy events for date range, optionally restricted to given service IDs."""
        cursor = self._execute_copy_events_query(start_date, end_date, service_ids)
        return [dict(row) for row in cursor.fetchall()]

    def iter_copy_events(
        self, start_date: str, end_date: str, service_ids: list[int] | None = None
    ) -> Generator[dict[str, Any], None, None]:
        """Yield copy event rows one at a time (streaming; avoids loading all into memory).

        Executes the same query as query_copy_events but yields each row
        individually so callers can process large result sets without
        materialising the entire list (#27).
        """
        cursor = self._execute_copy_events_query(start_date, end_date, service_ids)
        row = cursor.fetchone()
        while row is not None:
            yield dict(row)
            row = cursor.fetchone()

    # --- Service exclusions (missing-services report) ---

    def add_exclusion(
        self, service_date: str, service_slot: str, reason: str | None = None
    ) -> None:
        """Mark a (date, slot) as intentionally absent; upsert on conflict (#480).

        The date is normalized to ISO ``YYYY-MM-DD`` so it lines up with stored
        ``services.service_date`` values regardless of the caller's separators.
        """
        normalized = normalize_service_date(service_date)
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO service_exclusions (service_date, service_slot, reason, excluded_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(service_date, service_slot)
            DO UPDATE SET reason = excluded.reason, excluded_at = excluded.excluded_at
            """,
            (normalized, service_slot, reason, now),
        )
        self._maybe_commit()

    def remove_exclusion(self, service_date: str, service_slot: str) -> None:
        """Remove an intentional-exclusion marker for a (date, slot) (#480)."""
        normalized = normalize_service_date(service_date)
        self._conn.execute(
            "DELETE FROM service_exclusions WHERE service_date = ? AND service_slot = ?",
            (normalized, service_slot),
        )
        self._maybe_commit()

    def query_exclusions(self, start_date: str, end_date: str) -> list[dict]:
        """Return intentional-exclusion rows within the inclusive date range."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT id, service_date, service_slot, reason, excluded_at
            FROM service_exclusions
            WHERE service_date >= ? AND service_date <= ?
            ORDER BY service_date, service_slot
            """,
            (start_date, end_date),
        )
        return [dict(row) for row in cursor.fetchall()]

    def query_songs_missing_credits(self) -> list[dict]:
        """
        Return songs that have no credits (words_by, music_by, arranger all NULL).

        Includes the source_file from the most recent service where the song appeared,
        so the repair command can re-open the PPTX.
        """
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT DISTINCT s.id AS song_id, s.canonical_title, s.display_title,
                   se.id AS edition_id,
                   sv.source_file
            FROM songs s
            LEFT JOIN song_editions se ON se.song_id = s.id
            JOIN service_songs ss ON ss.song_id = s.id
            JOIN services sv ON ss.service_id = sv.id
            WHERE (se.words_by IS NULL AND se.music_by IS NULL AND se.arranger IS NULL)
               OR se.id IS NULL
            ORDER BY s.display_title
            """
        )
        return [dict(row) for row in cursor.fetchall()]

    def update_song_edition_credits(
        self,
        song_id: int,
        words_by: str | None = None,
        music_by: str | None = None,
        arranger: str | None = None,
    ) -> None:
        """
        Update or insert credits on a song's edition row, then backfill
        copy_events and service_songs rows that have NULL edition links.

        If a NULL-credit edition row exists, updates it in place.
        If no edition row exists, inserts one.
        """
        cursor = self._conn.cursor()

        # Check for an existing edition with no credits
        cursor.execute(
            """
            SELECT id FROM song_editions
            WHERE song_id = ?
              AND words_by IS NULL AND music_by IS NULL AND arranger IS NULL
            LIMIT 1
            """,
            (song_id,),
        )
        row = cursor.fetchone()

        if row:
            edition_id = row[0]
            cursor.execute(
                """
                UPDATE song_editions
                SET words_by = ?, music_by = ?, arranger = ?
                WHERE id = ?
                """,
                (words_by, music_by, arranger, edition_id),
            )
        else:
            # Insert a new edition with only credits (no publisher)
            cursor.execute(
                """
                INSERT INTO song_editions (song_id, words_by, music_by, arranger)
                VALUES (?, ?, ?, ?)
                """,
                (song_id, words_by, music_by, arranger),
            )
            edition_id = cursor.lastrowid

        # Backfill NULL edition links in copy_events and service_songs
        cursor.execute(
            "UPDATE copy_events SET song_edition_id = ?"
            " WHERE song_id = ? AND song_edition_id IS NULL",
            (edition_id, song_id),
        )
        cursor.execute(
            "UPDATE service_songs SET song_edition_id = ?"
            " WHERE song_id = ? AND song_edition_id IS NULL",
            (edition_id, song_id),
        )

        self._maybe_commit()

    def query_leader_top_songs(
        self, leader: str, min_count: int = 2
    ) -> list[dict[str, Any]]:
        """Return top songs for a leader with at least min_count services."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT s.id AS song_id, s.display_title, s.canonical_title,
                   se.words_by, se.music_by, se.arranger,
                   COUNT(DISTINCT ss.service_id) AS performance_count
            FROM service_songs ss
            JOIN services sv ON ss.service_id = sv.id
            JOIN songs s ON ss.song_id = s.id
            LEFT JOIN song_editions se ON ss.song_edition_id = se.id
            WHERE LOWER(COALESCE(sv.song_leader, '')) LIKE LOWER(?) ESCAPE '\\'
            GROUP BY s.id
            HAVING COUNT(DISTINCT ss.service_id) >= ?
            ORDER BY performance_count DESC, s.display_title
            """,
            (f"%{_escape_like(leader)}%", min_count),
        )
        return [dict(row) for row in cursor.fetchall()]

    def query_leader_service_count(self, leader: str) -> int:
        """Return count of services led by the given leader (partial match)."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT COUNT(*) FROM services
            WHERE LOWER(COALESCE(song_leader, '')) LIKE LOWER(?) ESCAPE '\\'
            """,
            (f"%{_escape_like(leader)}%",),
        )
        row = cursor.fetchone()
        return row[0] if row else 0

    def query_all_leaders(self) -> list[dict[str, Any]]:
        """Return all distinct leaders with their service counts."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT COALESCE(song_leader, 'Unknown') AS leader,
                   COUNT(DISTINCT id) AS service_count
            FROM services
            GROUP BY LOWER(COALESCE(song_leader, 'Unknown'))
            ORDER BY service_count DESC
            """,
        )
        return [dict(row) for row in cursor.fetchall()]

    def query_distinct_service_names(self) -> list[str]:
        """Distinct service_name values sorted alphabetically (for filter dropdowns)."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT DISTINCT service_name FROM services"
            " WHERE service_name IS NOT NULL ORDER BY service_name",
        )
        return [row[0] for row in cursor.fetchall()]

    def query_distinct_song_leaders(self) -> list[str]:
        """Distinct non-null song_leader values sorted alphabetically."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT DISTINCT song_leader FROM services"
            " WHERE song_leader IS NOT NULL AND song_leader != '' ORDER BY song_leader",
        )
        return [row[0] for row in cursor.fetchall()]

    def query_distinct_preachers(self) -> list[str]:
        """Distinct non-null preacher values sorted alphabetically."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT DISTINCT preacher FROM services"
            " WHERE preacher IS NOT NULL AND preacher != '' ORDER BY preacher",
        )
        return [row[0] for row in cursor.fetchall()]

    # --- Deletions ---

    def delete_service_data(self, service_id: int) -> None:
        """Delete all data for a service (for idempotent re-import)."""
        cursor = self._conn.cursor()

        # Delete copy events
        cursor.execute("DELETE FROM copy_events WHERE service_id = ?", (service_id,))

        # Delete service songs
        cursor.execute("DELETE FROM service_songs WHERE service_id = ?", (service_id,))

        # Delete service
        cursor.execute("DELETE FROM services WHERE id = ?", (service_id,))

        self._maybe_commit()

    # ------------------------------------------------------------------
    # Import job methods (#45)
    # ------------------------------------------------------------------

    def create_import_job(
        self,
        job_id: str,
        filename: str,
        started_at: str | None = None,
    ) -> None:
        """Insert a new import job record with status='pending'."""
        ts = started_at if started_at is not None else datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO import_jobs (job_id, filename, status, started_at)
            VALUES (?, ?, 'pending', ?)
            """,
            (job_id, filename, ts),
        )
        self._maybe_commit()
        _log.info("import_job job_id=%s status=pending filename=%s", job_id, filename)

    def get_import_job(self, job_id: str) -> dict[str, Any] | None:
        """Return a single import job row, or None if not found."""
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM import_jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def update_import_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        songs_imported: int | None = None,
        error_message: str | None = None,
        service_date: str | None = None,
        service_name: str | None = None,
        song_leader: str | None = None,
        preacher: str | None = None,
        sermon_title: str | None = None,
        songs_json: str | None = None,
        anomalies_json: str | None = None,
        ocr_model: str | None = None,
        ocr_calls: int | None = None,
        **_extra_kwargs: Any,
    ) -> None:
        """Update mutable fields on an import job record.

        Raises ValueError if any unexpected field name is passed via **kwargs
        so that callers cannot inject arbitrary SQL column names (issue #100).
        """
        for field_name in _extra_kwargs:
            if field_name not in _IMPORT_JOB_MUTABLE_FIELDS:
                raise ValueError(
                    f"Unknown field for update_import_job: {field_name!r}. "
                    f"Allowed fields: {sorted(_IMPORT_JOB_MUTABLE_FIELDS)}"
                )

        sets: list[str] = []
        params: list[Any] = []
        if status is not None:
            sets.append("status = ?")
            params.append(status)
            if status in ("complete", "failed"):
                sets.append("completed_at = ?")
                params.append(datetime.now(timezone.utc).isoformat())
        if songs_imported is not None:
            sets.append("songs_imported = ?")
            params.append(songs_imported)
        if error_message is not None:
            sets.append("error_message = ?")
            params.append(error_message)
        if service_date is not None:
            sets.append("service_date = ?")
            params.append(service_date)
        if service_name is not None:
            sets.append("service_name = ?")
            params.append(service_name)
        if song_leader is not None:
            sets.append("song_leader = ?")
            params.append(song_leader)
        if preacher is not None:
            sets.append("preacher = ?")
            params.append(preacher)
        if sermon_title is not None:
            sets.append("sermon_title = ?")
            params.append(sermon_title)
        if songs_json is not None:
            sets.append("songs_json = ?")
            params.append(songs_json)
        if anomalies_json is not None:
            sets.append("anomalies_json = ?")
            params.append(anomalies_json)
        if ocr_model is not None:
            sets.append("ocr_model = ?")
            params.append(ocr_model)
        if ocr_calls is not None:
            sets.append("ocr_calls = ?")
            params.append(ocr_calls)
        if not sets:
            return
        # Build the SET clause from whitelisted column names only.
        # Each entry in `sets` is a hardcoded literal like "status = ?" —
        # never derived from user input — so this join is safe.
        set_clause = ", ".join(sets)
        params.append(job_id)
        self._conn.execute(
            "UPDATE import_jobs SET " + set_clause + " WHERE job_id = ?",
            params,
        )
        self._maybe_commit()
        _log.info("import_job job_id=%s status=%s", job_id, status)

    def list_import_jobs(self) -> list[dict[str, Any]]:
        """Return all import job rows, newest first."""
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM import_jobs ORDER BY started_at DESC")
        return [dict(row) for row in cursor.fetchall()]

    def purge_old_import_jobs(self, days: int = 90, keep: int | None = None) -> None:
        """Delete old import job records.

        Two modes (mutually usable; *keep* takes priority when provided):

        * ``keep=N`` — retain the N most-recent jobs by ``started_at`` and
          delete everything else.  ``keep=0`` deletes all records.
        * ``days=N`` (original behaviour, default 90) — delete records whose
          ``started_at`` date is strictly older than *days* days ago.

        Args:
            days: Used only when *keep* is None.  Delete jobs older than this
                  many days.
            keep: If specified, keep only this many jobs (newest first).
        """
        if keep is None and days < 0:
            raise ValueError(f"days must be >= 0, got {days}")
        if keep is not None:
            # Use a sub-select to identify the IDs to keep, then delete the rest.
            self._conn.execute(
                """
                DELETE FROM import_jobs
                WHERE job_id NOT IN (
                    SELECT job_id FROM import_jobs
                    ORDER BY started_at DESC
                    LIMIT ?
                )
                """,
                (keep,),
            )
        else:
            threshold = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
            self._conn.execute(
                "DELETE FROM import_jobs WHERE date(started_at) < ?",
                (threshold,),
            )
        self._maybe_commit()

    # ------------------------------------------------------------------
    # Web query methods (moved from web/app.py — #166)
    # ------------------------------------------------------------------

    _SONGS_SORT_COLS: frozenset[str] = frozenset(
        {"display_title", "words_by", "music_by", "arranger", "performance_count"}
    )
    _SERVICES_SORT_COLS: frozenset[str] = frozenset(
        {"service_date", "service_name", "song_leader", "preacher", "song_count"}
    )

    def count_songs(self) -> int:
        """Return the total number of unique songs in the database."""
        cursor = self._conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM songs")
        return int(cursor.fetchone()[0])

    def query_songs_paginated(
        self,
        search: str | None = None,
        sort: str = "performance_count",
        sort_dir: str = "desc",
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return songs with performance count, optionally filtered and sorted."""
        sort = _safe_order_by(sort, self._SONGS_SORT_COLS)
        order = f"{sort} {_safe_sort_dir(sort_dir)}, s.display_title, s.id"
        cursor = self._conn.cursor()
        # Choose one display edition per song. Prefer the edition from the most
        # recent service that explicitly referenced one; for songs never linked
        # to an edition, fall back to the newest edition row.
        edition_join = """
            LEFT JOIN song_editions se ON se.id = COALESCE(
                (
                    SELECT recent_ss.song_edition_id
                    FROM service_songs recent_ss
                    JOIN services recent_sv ON recent_sv.id = recent_ss.service_id
                    WHERE recent_ss.song_id = s.id
                      AND recent_ss.song_edition_id IS NOT NULL
                    ORDER BY recent_sv.service_date DESC,
                             recent_sv.id DESC,
                             recent_ss.id DESC
                    LIMIT 1
                ),
                (
                    SELECT fallback_se.id
                    FROM song_editions fallback_se
                    WHERE fallback_se.song_id = s.id
                    ORDER BY fallback_se.id DESC
                    LIMIT 1
                )
            )
        """
        base = """
            SELECT s.id, s.display_title, s.canonical_title,
                   se.words_by, se.music_by, se.arranger,
                   COUNT(DISTINCT ss.service_id) AS performance_count
            FROM songs s
        """ + edition_join + """
            LEFT JOIN service_songs ss ON ss.song_id = s.id
        """
        count_base = """
            SELECT COUNT(DISTINCT s.id)
            FROM songs s
        """ + edition_join + """
            LEFT JOIN service_songs ss ON ss.song_id = s.id
        """
        offset = (page - 1) * per_page
        # COUNT and SELECT share one snapshot so the total can't disagree with
        # the rows when a concurrent import commits between them (#415).
        with self._read_snapshot():
            if search:
                like = f"%{_escape_like(search)}%"
                where = """
                    WHERE (LOWER(s.display_title) LIKE LOWER(?) ESCAPE '\\'
                       OR EXISTS (
                           SELECT 1 FROM song_editions search_se
                           WHERE search_se.song_id = s.id
                             AND (
                               LOWER(COALESCE(search_se.words_by, ''))
                                   LIKE LOWER(?) ESCAPE '\\'
                               OR LOWER(COALESCE(search_se.music_by, ''))
                                   LIKE LOWER(?) ESCAPE '\\'
                             )
                       ))
                """
                cursor.execute(count_base + where, (like, like, like))
                total: int = cursor.fetchone()[0]
                cursor.execute(
                    base
                    + where
                    + "GROUP BY s.id, s.display_title, s.canonical_title, "
                    + "se.words_by, se.music_by, se.arranger "
                    + "ORDER BY "
                    + order
                    + " LIMIT ? OFFSET ?",
                    (like, like, like, per_page, offset),
                )
            else:
                cursor.execute(count_base)
                total = cursor.fetchone()[0]
                cursor.execute(
                    base
                    + "GROUP BY s.id, s.display_title, s.canonical_title, "
                    + "se.words_by, se.music_by, se.arranger "
                    + "ORDER BY "
                    + order
                    + " LIMIT ? OFFSET ?",
                    (per_page, offset),
                )
            rows = [dict(row) for row in cursor.fetchall()]
        return rows, total

    def query_all_services_paginated(
        self,
        sort: str = "service_date",
        sort_dir: str = "desc",
        q_service: str = "",
        q_leader: str = "",
        q_preacher: str = "",
        q_sermon: str = "",
        start_date: str = "",
        end_date: str = "",
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return services with optional filtering, sorting, and pagination."""
        where_clauses: list[str] = []
        params: list[Any] = []
        if q_service:
            where_clauses.append("LOWER(sv.service_name) LIKE LOWER(?) ESCAPE '\\'")
            params.append(f"%{_escape_like(q_service)}%")
        if q_leader:
            where_clauses.append("LOWER(COALESCE(sv.song_leader,'')) LIKE LOWER(?) ESCAPE '\\'")
            params.append(f"%{_escape_like(q_leader)}%")
        if q_preacher:
            where_clauses.append("LOWER(COALESCE(sv.preacher,'')) LIKE LOWER(?) ESCAPE '\\'")
            params.append(f"%{_escape_like(q_preacher)}%")
        if q_sermon:
            where_clauses.append("LOWER(COALESCE(sv.sermon_title,'')) LIKE LOWER(?) ESCAPE '\\'")
            params.append(f"%{_escape_like(q_sermon)}%")
        if start_date:
            where_clauses.append("sv.service_date >= ?")
            params.append(start_date)
        if end_date:
            where_clauses.append("sv.service_date <= ?")
            params.append(end_date)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        sort = _safe_order_by(sort, self._SERVICES_SORT_COLS)
        order = f"{sort} {_safe_sort_dir(sort_dir)}, sv.service_name"
        offset = (page - 1) * per_page
        cursor = self._conn.cursor()
        # COUNT and SELECT share one snapshot for consistent pagination (#415).
        with self._read_snapshot():
            cursor.execute(
                f"SELECT COUNT(DISTINCT sv.id) FROM services sv {where_sql}",
                params,
            )
            total: int = cursor.fetchone()[0]
            cursor.execute(
                f"""
                SELECT sv.*, COUNT(DISTINCT ss.song_id) AS song_count
                FROM services sv
                LEFT JOIN service_songs ss ON ss.service_id = sv.id
                {where_sql}
                GROUP BY sv.id
                ORDER BY {order}
                LIMIT ? OFFSET ?
                """,
                params + [per_page, offset],
            )
            rows = [dict(row) for row in cursor.fetchall()]
        return rows, total

    # --- Cleanup queries (#266) ---

    def query_services_by_date(
        self, date: str, name_pattern: str | None = None
    ) -> list[dict[str, Any]]:
        """Return services matching *date*, optionally filtered by name pattern."""
        cursor = self._conn.cursor()
        if name_pattern:
            cursor.execute(
                """
                SELECT * FROM services
                WHERE service_date = ? AND LOWER(service_name) LIKE LOWER(?) ESCAPE '\\'
                ORDER BY id
                """,
                (date, f"%{_escape_like(name_pattern)}%"),
            )
        else:
            cursor.execute(
                "SELECT * FROM services WHERE service_date = ? ORDER BY id",
                (date,),
            )
        return [dict(row) for row in cursor.fetchall()]

    def query_orphaned_songs(self) -> list[dict[str, Any]]:
        """Return songs that have no service_songs rows (0 performances)."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT s.id AS song_id, s.canonical_title, s.display_title
            FROM songs s
            LEFT JOIN service_songs ss ON ss.song_id = s.id
            WHERE ss.id IS NULL
            ORDER BY s.display_title
            """
        )
        return [dict(row) for row in cursor.fetchall()]

    def query_duplicate_services(self) -> list[dict[str, Any]]:
        """Return services that share (service_date, service_name) but differ in source_hash."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT s.*
            FROM services s
            INNER JOIN (
                SELECT service_date, service_name
                FROM services
                GROUP BY service_date, service_name
                HAVING COUNT(DISTINCT source_hash) > 1
            ) dup ON s.service_date = dup.service_date
                  AND s.service_name = dup.service_name
            ORDER BY s.service_date, s.service_name, s.id
            """
        )
        return [dict(row) for row in cursor.fetchall()]

    def dedup_services(self, *, dry_run: bool = False) -> list[dict[str, Any]]:
        """Remove duplicate service rows, keeping the highest-id row per (date, name) group.

        Returns a list of dicts describing each removed row.  When *dry_run* is
        True the rows are identified but not deleted.
        """
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT *
            FROM services
            WHERE id NOT IN (
                SELECT MAX(id) FROM services GROUP BY service_date, service_name
            )
            ORDER BY service_date, service_name, id
            """
        )
        losers = [dict(row) for row in cursor.fetchall()]
        if not losers or dry_run:
            return losers

        loser_ids = [row["id"] for row in losers]
        placeholders = ",".join("?" * len(loser_ids))
        cursor.execute(
            f"DELETE FROM copy_events WHERE service_id IN ({placeholders})", loser_ids
        )
        cursor.execute(
            f"DELETE FROM service_songs WHERE service_id IN ({placeholders})", loser_ids
        )
        cursor.execute(
            f"DELETE FROM services WHERE id IN ({placeholders})", loser_ids
        )
        self._maybe_commit()
        return losers

    def normalize_service_dates(self, *, dry_run: bool = False) -> list[dict[str, Any]]:
        """Rewrite non-ISO service dates to canonical ``YYYY-MM-DD`` (#387).

        Returns a report: one dict per row whose stored date differs from its
        normalized form, with ``service_id``, ``old_date``, ``new_date`` and a
        ``collision`` flag.  A collision means another service already occupies
        ``(new_date, service_name)`` — that row is reported but NOT rewritten,
        to avoid violating ``UNIQUE(service_date, service_name)``.  When
        *dry_run* is True nothing is written.
        """
        from worship_catalog.normalize import normalize_service_date

        cursor = self._conn.cursor()
        cursor.execute("SELECT id, service_date, service_name FROM services")
        rows = [dict(r) for r in cursor.fetchall()]

        report: list[dict[str, Any]] = []
        for row in rows:
            old_date = row["service_date"]
            new_date = normalize_service_date(old_date)
            if new_date == old_date:
                continue
            cursor.execute(
                """SELECT id FROM services
                   WHERE service_date = ? AND service_name = ? AND id != ?""",
                (new_date, row["service_name"], row["id"]),
            )
            collision = cursor.fetchone() is not None
            report.append({
                "service_id": row["id"],
                "old_date": old_date,
                "new_date": new_date,
                "service_name": row["service_name"],
                "collision": collision,
            })

        if dry_run:
            return report

        for item in report:
            if item["collision"]:
                continue
            cursor.execute(
                "UPDATE services SET service_date = ? WHERE id = ?",
                (item["new_date"], item["service_id"]),
            )
        self._maybe_commit()
        return report

    def delete_song(self, song_id: int) -> None:
        """Delete a song, its editions, and any related copy_events."""
        cursor = self._conn.cursor()
        cursor.execute("DELETE FROM copy_events WHERE song_id = ?", (song_id,))
        cursor.execute("DELETE FROM service_songs WHERE song_id = ?", (song_id,))
        cursor.execute("DELETE FROM song_editions WHERE song_id = ?", (song_id,))
        cursor.execute("DELETE FROM songs WHERE id = ?", (song_id,))
        self._maybe_commit()

    def query_song_by_id(self, song_id: int) -> dict[str, Any] | None:
        """Return a single song row or None."""
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM songs WHERE id = ?", (song_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def query_song_editions(self, song_id: int) -> list[dict[str, Any]]:
        """Return all editions for a song."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT * FROM song_editions WHERE song_id = ? ORDER BY id",
            (song_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def query_song_services(self, song_id: int) -> list[dict[str, Any]]:
        """Return all services where a song was performed."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT sv.id AS service_id, sv.service_date, sv.service_name, sv.song_leader,
                   ss.ordinal,
                   GROUP_CONCAT(DISTINCT ce.reproduction_type) AS copy_types
            FROM services sv
            JOIN service_songs ss ON ss.service_id = sv.id
            LEFT JOIN copy_events ce ON ce.service_id = sv.id
                                     AND ce.song_id = ss.song_id
                                     AND ce.reportable = 1
            WHERE ss.song_id = ?
            GROUP BY sv.id
            ORDER BY sv.service_date DESC
            """,
            (song_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def query_service_by_id(self, service_id: int) -> dict[str, Any] | None:
        """Return a single service row or None."""
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM services WHERE id = ?", (service_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def query_service_songs(self, service_id: int) -> list[dict[str, Any]]:
        """Return songs for a service in setlist order, with full credits."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT ss.ordinal, ss.occurrences,
                   s.id AS song_id, s.display_title, s.canonical_title,
                   se.publisher, se.words_by, se.music_by, se.arranger, se.copyright_notice,
                   GROUP_CONCAT(ce.reproduction_type, ', ') AS copy_types
            FROM service_songs ss
            JOIN songs s ON ss.song_id = s.id
            LEFT JOIN song_editions se ON ss.song_edition_id = se.id
            LEFT JOIN copy_events ce ON ce.service_id = ss.service_id
                                     AND ce.song_id = ss.song_id
                                     AND ce.reportable = 1
            WHERE ss.service_id = ?
            GROUP BY ss.id
            ORDER BY ss.ordinal
            """,
            (service_id,),
        )
        return [dict(row) for row in cursor.fetchall()]
