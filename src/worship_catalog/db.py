"""SQLite database schema and operations."""

import logging
import sqlite3
import warnings
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger("worship_catalog.db")

# Bump this integer whenever the schema changes in a backwards-incompatible way.
# connect() will raise SchemaVersionError if the on-disk version is higher than
# this value (i.e. the DB was created by a newer version of the code).
_SCHEMA_VERSION: int = 1

# Whitelist of column names that update_import_job is allowed to SET.
# Any key not in this set will raise ValueError — prevents SQL injection
# via dynamic field names (issue #100).
_IMPORT_JOB_MUTABLE_FIELDS: frozenset[str] = frozenset(
    {"status", "completed_at", "songs_imported", "error_message"}
)


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


class SchemaVersionError(RuntimeError):
    """Raised when the database schema version is incompatible with this code."""


class Database:
    """SQLite database interface for worship catalog."""

    def __init__(self, db_path: Path | str = "data/worship.db"):
        """Initialize database connection."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn: sqlite3.Connection | None = None
        self._in_transaction: bool = False

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
        """Close database connection."""
        if self.conn:
            self.conn.close()

    @contextmanager
    def transaction(self) -> Generator[None, None, None]:
        """Context manager that wraps multiple DB calls in a single transaction.

        On success: commits once when the block exits.
        On exception: rolls back all changes and re-raises.
        """
        self._in_transaction = True
        try:
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

    def init_schema(self) -> None:
        """Create database schema."""
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

        self._conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        self._maybe_commit()

    # --- Songs ---

    def insert_or_get_song(
        self, canonical_title: str, display_title: str
    ) -> int:
        """Insert or get song by canonical title. Returns song_id."""
        cursor = self._conn.cursor()

        # Try to get existing
        cursor.execute(
            "SELECT id FROM songs WHERE canonical_title = ?", (canonical_title,)
        )
        row = cursor.fetchone()
        if row:
            return row[0]

        # Insert new
        cursor.execute(
            "INSERT INTO songs (canonical_title, display_title) VALUES (?, ?)",
            (canonical_title, display_title),
        )
        self._maybe_commit()
        return cursor.lastrowid

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

        # Try to get existing - handle NULL comparisons explicitly
        cursor.execute(
            """
            SELECT id FROM song_editions
            WHERE song_id = ?
            AND (publisher = ? OR (publisher IS NULL AND ? IS NULL))
            AND (words_by = ? OR (words_by IS NULL AND ? IS NULL))
            AND (music_by = ? OR (music_by IS NULL AND ? IS NULL))
            AND (arranger = ? OR (arranger IS NULL AND ? IS NULL))
            """,
            (
                song_id,
                publisher,
                publisher,
                words_by,
                words_by,
                music_by,
                music_by,
                arranger,
                arranger,
            ),
        )
        row = cursor.fetchone()
        if row:
            return row[0]

        # Insert new
        cursor.execute(
            """
            INSERT INTO song_editions
            (song_id, publisher, words_by, music_by, arranger, copyright_notice)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (song_id, publisher, words_by, music_by, arranger, copyright_notice),
        )
        self._maybe_commit()
        return cursor.lastrowid

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
        """Insert or update service. Returns service_id."""
        cursor = self._conn.cursor()

        # Check if exists
        cursor.execute(
            """
            SELECT id FROM services
            WHERE service_date = ? AND service_name = ? AND source_hash = ?
            """,
            (service_date, service_name, source_hash),
        )
        row = cursor.fetchone()

        imported_at = datetime.now(timezone.utc).isoformat()

        if row:
            # Update existing
            service_id = row[0]
            cursor.execute(
                """
                UPDATE services
                SET song_leader = ?, preacher = ?, sermon_title = ?, imported_at = ?
                WHERE id = ?
                """,
                (song_leader, preacher, sermon_title, imported_at, service_id),
            )
        else:
            # Insert new
            cursor.execute(
                """
                INSERT INTO services
                (service_date, service_name, source_file, source_hash,
                 song_leader, preacher, sermon_title, imported_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
            service_id = cursor.lastrowid

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
        cursor.execute(
            """
            SELECT id FROM copy_events
            WHERE service_id = ? AND song_id = ? AND reproduction_type = ?
            AND (song_edition_id = ? OR (song_edition_id IS NULL AND ? IS NULL))
            """,
            (service_id, song_id, reproduction_type, song_edition_id, song_edition_id),
        )
        row = cursor.fetchone()
        if row:
            return row[0]

        # Insert new
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

    # --- Queries ---

    def query_services(
        self, start_date: str, end_date: str, song_leader: str | None = None
    ) -> list[dict]:
        """Query services by date range, with optional case-insensitive song leader filter."""
        cursor = self._conn.cursor()
        if song_leader:
            cursor.execute(
                """
                SELECT * FROM services
                WHERE service_date >= ? AND service_date <= ?
                  AND LOWER(song_leader) LIKE LOWER(?)
                ORDER BY service_date
                """,
                (start_date, end_date, f"%{song_leader}%"),
            )
        else:
            cursor.execute(
                """
                SELECT * FROM services
                WHERE service_date >= ? AND service_date <= ?
                ORDER BY service_date
                """,
                (start_date, end_date),
            )
        return [dict(row) for row in cursor.fetchall()]

    def query_copy_events(
        self, start_date: str, end_date: str, service_ids: list[int] | None = None
    ) -> list[dict]:
        """Query copy events for date range, optionally restricted to given service IDs."""
        cursor = self._conn.cursor()
        if service_ids is not None:
            placeholders = ",".join("?" * len(service_ids))
            cursor.execute(
                f"""
                SELECT ce.*, s.canonical_title, s.display_title, sv.service_date, sv.service_name,
                       se.words_by, se.music_by, se.arranger
                FROM copy_events ce
                JOIN services sv ON ce.service_id = sv.id
                JOIN songs s ON ce.song_id = s.id
                LEFT JOIN song_editions se ON ce.song_edition_id = se.id
                WHERE sv.service_date >= ? AND sv.service_date <= ?
                  AND ce.reportable = 1
                  AND ce.service_id IN ({placeholders})
                ORDER BY sv.service_date, s.canonical_title
                """,
                (start_date, end_date, *service_ids),
            )
        else:
            cursor.execute(
                """
                SELECT ce.*, s.canonical_title, s.display_title, sv.service_date, sv.service_name,
                       se.words_by, se.music_by, se.arranger
                FROM copy_events ce
                JOIN services sv ON ce.service_id = sv.id
                JOIN songs s ON ce.song_id = s.id
                LEFT JOIN song_editions se ON ce.song_edition_id = se.id
                WHERE sv.service_date >= ? AND sv.service_date <= ? AND ce.reportable = 1
                ORDER BY sv.service_date, s.canonical_title
                """,
                (start_date, end_date),
            )
        return [dict(row) for row in cursor.fetchall()]

    def iter_copy_events(
        self, start_date: str, end_date: str, service_ids: list[int] | None = None
    ) -> Generator[dict[str, Any], None, None]:
        """Yield copy event rows one at a time (streaming; avoids loading all into memory).

        Executes the same query as query_copy_events but yields each row
        individually so callers can process large result sets without
        materialising the entire list (#27).
        """
        cursor = self._conn.cursor()
        if service_ids is not None:
            placeholders = ",".join("?" * len(service_ids))
            cursor.execute(
                f"""
                SELECT ce.*, s.canonical_title, s.display_title, sv.service_date, sv.service_name,
                       se.words_by, se.music_by, se.arranger
                FROM copy_events ce
                JOIN services sv ON ce.service_id = sv.id
                JOIN songs s ON ce.song_id = s.id
                LEFT JOIN song_editions se ON ce.song_edition_id = se.id
                WHERE sv.service_date >= ? AND sv.service_date <= ?
                  AND ce.reportable = 1
                  AND ce.service_id IN ({placeholders})
                ORDER BY sv.service_date, s.canonical_title
                """,
                (start_date, end_date, *service_ids),
            )
        else:
            cursor.execute(
                """
                SELECT ce.*, s.canonical_title, s.display_title, sv.service_date, sv.service_name,
                       se.words_by, se.music_by, se.arranger
                FROM copy_events ce
                JOIN services sv ON ce.service_id = sv.id
                JOIN songs s ON ce.song_id = s.id
                LEFT JOIN song_editions se ON ce.song_edition_id = se.id
                WHERE sv.service_date >= ? AND sv.service_date <= ? AND ce.reportable = 1
                ORDER BY sv.service_date, s.canonical_title
                """,
                (start_date, end_date),
            )
        row = cursor.fetchone()
        while row is not None:
            yield dict(row)
            row = cursor.fetchone()

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
            WHERE LOWER(COALESCE(sv.song_leader, '')) LIKE LOWER(?)
            GROUP BY s.id
            HAVING COUNT(DISTINCT ss.service_id) >= ?
            ORDER BY performance_count DESC, s.display_title
            """,
            (f"%{leader}%", min_count),
        )
        return [dict(row) for row in cursor.fetchall()]

    def query_leader_service_count(self, leader: str) -> int:
        """Return count of services led by the given leader (partial match)."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT COUNT(*) FROM services
            WHERE LOWER(COALESCE(song_leader, '')) LIKE LOWER(?)
            """,
            (f"%{leader}%",),
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

    def purge_old_import_jobs(self, days: int = 90) -> None:
        """Delete import job records whose started_at date is older than *days* days."""
        threshold = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        self._conn.execute(
            "DELETE FROM import_jobs WHERE date(started_at) < ?",
            (threshold,),
        )
        self._maybe_commit()
