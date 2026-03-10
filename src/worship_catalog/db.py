"""SQLite database schema and operations."""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from worship_catalog.pptx_reader import compute_file_hash


class Database:
    """SQLite database interface for worship catalog."""

    def __init__(self, db_path: Path | str = "data/worship.db"):
        """Initialize database connection."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn: Optional[sqlite3.Connection] = None

    def connect(self) -> sqlite3.Connection:
        """Connect to database."""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        return self.conn

    def close(self) -> None:
        """Close database connection."""
        if self.conn:
            self.conn.close()

    def init_schema(self) -> None:
        """Create database schema."""
        if not self.conn:
            self.connect()

        cursor = self.conn.cursor()

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

        self.conn.commit()

    def insert_or_get_song(
        self, canonical_title: str, display_title: str
    ) -> int:
        """Insert or get song by canonical title. Returns song_id."""
        cursor = self.conn.cursor()

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
        self.conn.commit()
        return cursor.lastrowid

    def insert_or_get_song_edition(
        self,
        song_id: int,
        publisher: Optional[str] = None,
        words_by: Optional[str] = None,
        music_by: Optional[str] = None,
        arranger: Optional[str] = None,
        copyright_notice: Optional[str] = None,
    ) -> int:
        """Insert or get song edition. Returns edition_id."""
        cursor = self.conn.cursor()

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
        self.conn.commit()
        return cursor.lastrowid

    def insert_or_update_service(
        self,
        service_date: str,
        service_name: str,
        source_file: str,
        source_hash: str,
        song_leader: Optional[str] = None,
        preacher: Optional[str] = None,
        sermon_title: Optional[str] = None,
    ) -> int:
        """Insert or update service. Returns service_id."""
        cursor = self.conn.cursor()

        # Check if exists
        cursor.execute(
            """
            SELECT id FROM services
            WHERE service_date = ? AND service_name = ? AND source_hash = ?
            """,
            (service_date, service_name, source_hash),
        )
        row = cursor.fetchone()

        imported_at = datetime.now().isoformat()

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
                (service_date, service_name, source_file, source_hash, song_leader, preacher, sermon_title, imported_at)
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

        self.conn.commit()
        return service_id

    def insert_service_song(
        self,
        service_id: int,
        song_id: int,
        ordinal: int,
        song_edition_id: Optional[int] = None,
        first_slide_index: Optional[int] = None,
        last_slide_index: Optional[int] = None,
        occurrences: int = 1,
    ) -> int:
        """Insert service song. Returns service_song_id."""
        cursor = self.conn.cursor()

        cursor.execute(
            """
            INSERT INTO service_songs
            (service_id, song_id, song_edition_id, ordinal, first_slide_index, last_slide_index, occurrences)
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
        self.conn.commit()
        return cursor.lastrowid

    def insert_copy_event(
        self,
        service_id: int,
        song_id: int,
        reproduction_type: str,
        count: int = 1,
        reportable: bool = True,
        song_edition_id: Optional[int] = None,
    ) -> int:
        """Insert copy event. Returns event_id."""
        cursor = self.conn.cursor()

        cursor.execute(
            """
            INSERT INTO copy_events
            (service_id, song_id, song_edition_id, reproduction_type, count, reportable)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (service_id, song_id, song_edition_id, reproduction_type, count, int(reportable)),
        )
        self.conn.commit()
        return cursor.lastrowid

    def insert_or_get_copy_event(
        self,
        service_id: int,
        song_id: int,
        reproduction_type: str,
        count: int = 1,
        reportable: bool = True,
        song_edition_id: Optional[int] = None,
    ) -> int:
        """Insert or get copy event. Returns event_id."""
        cursor = self.conn.cursor()

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
        self.conn.commit()
        return cursor.lastrowid

    def query_services(
        self, start_date: str, end_date: str, song_leader: Optional[str] = None
    ) -> list[dict]:
        """Query services by date range, with optional case-insensitive song leader filter."""
        cursor = self.conn.cursor()
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
        self, start_date: str, end_date: str, service_ids: Optional[list[int]] = None
    ) -> list[dict]:
        """Query copy events for date range, optionally restricted to given service IDs."""
        cursor = self.conn.cursor()
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

    def query_songs_missing_credits(self) -> list[dict]:
        """
        Return songs that have no credits (words_by, music_by, arranger all NULL).

        Includes the source_file from the most recent service where the song appeared,
        so the repair command can re-open the PPTX.
        """
        cursor = self.conn.cursor()
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
        words_by: Optional[str] = None,
        music_by: Optional[str] = None,
        arranger: Optional[str] = None,
    ) -> None:
        """
        Update or insert credits on a song's edition row, then backfill
        copy_events and service_songs rows that have NULL edition links.

        If a NULL-credit edition row exists, updates it in place.
        If no edition row exists, inserts one.
        """
        cursor = self.conn.cursor()

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
            "UPDATE copy_events SET song_edition_id = ? WHERE song_id = ? AND song_edition_id IS NULL",
            (edition_id, song_id),
        )
        cursor.execute(
            "UPDATE service_songs SET song_edition_id = ? WHERE song_id = ? AND song_edition_id IS NULL",
            (edition_id, song_id),
        )

        self.conn.commit()

    def delete_service_data(self, service_id: int) -> None:
        """Delete all data for a service (for idempotent re-import)."""
        cursor = self.conn.cursor()

        # Delete copy events
        cursor.execute("DELETE FROM copy_events WHERE service_id = ?", (service_id,))

        # Delete service songs
        cursor.execute("DELETE FROM service_songs WHERE service_id = ?", (service_id,))

        # Delete service
        cursor.execute("DELETE FROM services WHERE id = ?", (service_id,))

        self.conn.commit()
