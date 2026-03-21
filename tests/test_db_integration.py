"""Integration tests for database operations."""

import logging
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from worship_catalog.db import Database


@pytest.mark.integration
class TestDatabaseSchema:
    """Tests for database schema initialization."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()
            yield db
            db.close()

    def test_schema_initialization(self, temp_db):
        """Verify all tables are created."""
        cursor = temp_db.conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]

        assert "services" in tables
        assert "songs" in tables
        assert "song_editions" in tables
        assert "service_songs" in tables
        assert "copy_events" in tables

    def test_services_table_structure(self, temp_db):
        """Verify services table has correct columns."""
        cursor = temp_db.conn.cursor()
        cursor.execute("PRAGMA table_info(services)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        assert "id" in columns
        assert "service_date" in columns
        assert "service_name" in columns
        assert "song_leader" in columns
        assert "preacher" in columns
        assert "sermon_title" in columns
        assert "source_file" in columns
        assert "source_hash" in columns
        assert "imported_at" in columns

    def test_songs_table_structure(self, temp_db):
        """Verify songs table has correct columns."""
        cursor = temp_db.conn.cursor()
        cursor.execute("PRAGMA table_info(songs)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        assert "id" in columns
        assert "canonical_title" in columns
        assert "display_title" in columns
        assert "ccli_number" in columns
        assert "aliases_json" in columns
        assert "public_domain" in columns


@pytest.mark.integration
class TestServiceOperations:
    """Tests for service insertion and updates."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()
            yield db
            db.close()

    def test_insert_service(self, temp_db):
        """Insert a new service."""
        service_id = temp_db.insert_or_update_service(
            service_date="2026-02-15",
            service_name="Morning Worship",
            source_file="AM Worship 2026.02.15.pptx",
            source_hash="abc123",
            song_leader="Matt Shirel",
            preacher="David Morris",
            sermon_title="Love Never Fails",
        )

        assert service_id > 0

        # Verify in database
        cursor = temp_db.conn.cursor()
        cursor.execute("SELECT * FROM services WHERE id = ?", (service_id,))
        row = cursor.fetchone()
        assert row["service_date"] == "2026-02-15"
        assert row["service_name"] == "Morning Worship"
        assert row["song_leader"] == "Matt Shirel"

    def test_service_idempotency(self, temp_db):
        """Re-importing same service with same hash produces no new row."""
        # First insert
        service_id_1 = temp_db.insert_or_update_service(
            service_date="2026-02-15",
            service_name="Morning Worship",
            source_file="AM Worship 2026.02.15.pptx",
            source_hash="abc123",
            song_leader="Matt",
            preacher="David",
            sermon_title="Title1",
        )

        # Second insert with same hash
        service_id_2 = temp_db.insert_or_update_service(
            service_date="2026-02-15",
            service_name="Morning Worship",
            source_file="AM Worship 2026.02.15.pptx",
            source_hash="abc123",
            song_leader="Matthew",  # Different value
            preacher="David Morris",  # Different value
            sermon_title="Love Never Fails",  # Different value
        )

        # Should return same service_id
        assert service_id_1 == service_id_2

        # Verify only one row exists
        cursor = temp_db.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM services")
        count = cursor.fetchone()[0]
        assert count == 1

        # Verify values were updated
        cursor.execute("SELECT * FROM services WHERE id = ?", (service_id_1,))
        row = cursor.fetchone()
        assert row["song_leader"] == "Matthew"
        assert row["preacher"] == "David Morris"

    def test_service_unique_constraint(self, temp_db):
        """Duplicate service with same date/name/hash violates constraint."""
        temp_db.insert_or_update_service(
            service_date="2026-02-15",
            service_name="Morning Worship",
            source_file="file1.pptx",
            source_hash="hash1",
        )

        # This should update, not insert, due to idempotent logic
        service_id_2 = temp_db.insert_or_update_service(
            service_date="2026-02-15",
            service_name="Morning Worship",
            source_file="file2.pptx",  # Different file
            source_hash="hash1",  # Same hash
        )

        # Should return same ID (update case)
        assert service_id_2 > 0

        # Only one service should exist
        cursor = temp_db.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM services")
        count = cursor.fetchone()[0]
        assert count == 1


@pytest.mark.integration
class TestSongOperations:
    """Tests for song insertion and retrieval."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()
            yield db
            db.close()

    def test_insert_song(self, temp_db):
        """Insert a new song."""
        song_id = temp_db.insert_or_get_song("majesty", "Majesty")
        assert song_id > 0

        # Verify in database
        cursor = temp_db.conn.cursor()
        cursor.execute("SELECT * FROM songs WHERE id = ?", (song_id,))
        row = cursor.fetchone()
        assert row["canonical_title"] == "majesty"
        assert row["display_title"] == "Majesty"

    def test_song_get_existing(self, temp_db):
        """Getting an existing song returns same ID."""
        song_id_1 = temp_db.insert_or_get_song("majesty", "Majesty")
        song_id_2 = temp_db.insert_or_get_song("majesty", "Majesty (different display)")

        # Should return same canonical_title, so same ID
        assert song_id_1 == song_id_2

    def test_song_unique_canonical_title(self, temp_db):
        """Canonical titles must be unique."""
        song_id_1 = temp_db.insert_or_get_song("majesty", "Majesty")

        # Inserting with same canonical but different display should return same ID
        song_id_2 = temp_db.insert_or_get_song("majesty", "MAJESTY (Traditional)")
        assert song_id_1 == song_id_2

    def test_insert_multiple_songs(self, temp_db):
        """Insert multiple distinct songs."""
        song_id_1 = temp_db.insert_or_get_song("majesty", "Majesty")
        song_id_2 = temp_db.insert_or_get_song("mighty to save", "Mighty To Save")
        song_id_3 = temp_db.insert_or_get_song("he is my everything", "He is my Everything")

        assert song_id_1 != song_id_2
        assert song_id_2 != song_id_3
        assert song_id_1 != song_id_3

        cursor = temp_db.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM songs")
        count = cursor.fetchone()[0]
        assert count == 3


@pytest.mark.integration
class TestSongEditionOperations:
    """Tests for song edition insertion and retrieval."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()
            yield db
            db.close()

    def test_insert_song_edition(self, temp_db):
        """Insert a song edition."""
        song_id = temp_db.insert_or_get_song("majesty", "Majesty")
        edition_id = temp_db.insert_or_get_song_edition(
            song_id=song_id,
            publisher="Paperless Hymnal",
            words_by="Jack Hayford",
            music_by="Jack Hayford",
            arranger="Ken Young",
        )

        assert edition_id > 0

        # Verify in database
        cursor = temp_db.conn.cursor()
        cursor.execute("SELECT * FROM song_editions WHERE id = ?", (edition_id,))
        row = cursor.fetchone()
        assert row["song_id"] == song_id
        assert row["publisher"] == "Paperless Hymnal"
        assert row["arranger"] == "Ken Young"

    def test_edition_get_existing(self, temp_db):
        """Getting an existing edition returns same ID."""
        song_id = temp_db.insert_or_get_song("majesty", "Majesty")

        edition_id_1 = temp_db.insert_or_get_song_edition(
            song_id=song_id,
            publisher="Paperless Hymnal",
            words_by="Jack Hayford",
        )

        edition_id_2 = temp_db.insert_or_get_song_edition(
            song_id=song_id,
            publisher="Paperless Hymnal",
            words_by="Jack Hayford",
        )

        assert edition_id_1 == edition_id_2

    def test_edition_unique_constraint(self, temp_db):
        """Song editions must be unique by (song_id, publisher, credits)."""
        song_id = temp_db.insert_or_get_song("majesty", "Majesty")

        # Two different editions (different arranger)
        edition_id_1 = temp_db.insert_or_get_song_edition(
            song_id=song_id,
            publisher="Paperless Hymnal",
            words_by="Jack Hayford",
            arranger="Ken Young",
        )

        edition_id_2 = temp_db.insert_or_get_song_edition(
            song_id=song_id,
            publisher="Paperless Hymnal",
            words_by="Jack Hayford",
            arranger="John Smith",
        )

        assert edition_id_1 != edition_id_2


@pytest.mark.integration
class TestServiceSongOperations:
    """Tests for service-song linking."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()
            yield db
            db.close()

    def test_insert_service_song(self, temp_db):
        """Link a song to a service."""
        service_id = temp_db.insert_or_update_service(
            service_date="2026-02-15",
            service_name="Morning Worship",
            source_file="AM Worship 2026.02.15.pptx",
            source_hash="abc123",
        )

        song_id = temp_db.insert_or_get_song("majesty", "Majesty")

        ss_id = temp_db.insert_service_song(
            service_id=service_id,
            song_id=song_id,
            ordinal=1,
            first_slide_index=1,
            last_slide_index=2,
            occurrences=1,
        )

        assert ss_id > 0

        # Verify in database
        cursor = temp_db.conn.cursor()
        cursor.execute("SELECT * FROM service_songs WHERE id = ?", (ss_id,))
        row = cursor.fetchone()
        assert row["service_id"] == service_id
        assert row["song_id"] == song_id
        assert row["ordinal"] == 1

    def test_service_song_ordinal_uniqueness(self, temp_db):
        """Ordinal must be unique per service."""
        service_id = temp_db.insert_or_update_service(
            service_date="2026-02-15",
            service_name="Morning Worship",
            source_file="AM Worship 2026.02.15.pptx",
            source_hash="abc123",
        )

        song_id_1 = temp_db.insert_or_get_song("majesty", "Majesty")
        song_id_2 = temp_db.insert_or_get_song("mighty to save", "Mighty To Save")

        # Insert first song at ordinal 1
        ss_id_1 = temp_db.insert_service_song(
            service_id=service_id,
            song_id=song_id_1,
            ordinal=1,
        )

        # Try to insert another song at same ordinal - should fail
        with pytest.raises(sqlite3.IntegrityError):
            temp_db.insert_service_song(
                service_id=service_id,
                song_id=song_id_2,
                ordinal=1,
            )

        # But ordinal 2 should work
        ss_id_2 = temp_db.insert_service_song(
            service_id=service_id,
            song_id=song_id_2,
            ordinal=2,
        )
        assert ss_id_2 > 0


@pytest.mark.integration
class TestCopyEventOperations:
    """Tests for CCLI copy event creation."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()
            yield db
            db.close()

    def test_insert_copy_event(self, temp_db):
        """Insert a copy event."""
        service_id = temp_db.insert_or_update_service(
            service_date="2026-02-15",
            service_name="Morning Worship",
            source_file="AM Worship 2026.02.15.pptx",
            source_hash="abc123",
        )

        song_id = temp_db.insert_or_get_song("majesty", "Majesty")

        event_id = temp_db.insert_copy_event(
            service_id=service_id,
            song_id=song_id,
            reproduction_type="projection",
            count=1,
            reportable=True,
        )

        assert event_id > 0

    def test_copy_event_unique_constraint(self, temp_db):
        """Copy events must be unique by (service_id, song_id, edition_id, reproduction_type)."""
        service_id = temp_db.insert_or_update_service(
            service_date="2026-02-15",
            service_name="Morning Worship",
            source_file="AM Worship 2026.02.15.pptx",
            source_hash="abc123",
        )

        song_id = temp_db.insert_or_get_song("majesty", "Majesty")

        # Create a specific edition to avoid NULL issues with UNIQUE constraint
        edition_id = temp_db.insert_or_get_song_edition(
            song_id=song_id,
            publisher="Paperless Hymnal",
            words_by="Jack Hayford",
        )

        # Insert one event with non-NULL edition_id
        event_id_1 = temp_db.insert_copy_event(
            service_id=service_id,
            song_id=song_id,
            song_edition_id=edition_id,
            reproduction_type="projection",
            count=1,
        )

        # Try to insert duplicate - should fail
        with pytest.raises(sqlite3.IntegrityError):
            temp_db.insert_copy_event(
                service_id=service_id,
                song_id=song_id,
                song_edition_id=edition_id,
                reproduction_type="projection",
                count=1,
            )

        # But different reproduction_type should work
        event_id_2 = temp_db.insert_copy_event(
            service_id=service_id,
            song_id=song_id,
            song_edition_id=edition_id,
            reproduction_type="recording",
            count=1,
        )
        assert event_id_2 > 0


@pytest.mark.integration
class TestQueryOperations:
    """Tests for query operations."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()
            yield db
            db.close()

    def test_query_services_by_date_range(self, temp_db):
        """Query services by date range."""
        # Insert services on different dates
        temp_db.insert_or_update_service(
            service_date="2026-02-08",
            service_name="Morning Worship",
            source_file="file1.pptx",
            source_hash="hash1",
        )

        temp_db.insert_or_update_service(
            service_date="2026-02-15",
            service_name="Morning Worship",
            source_file="file2.pptx",
            source_hash="hash2",
        )

        temp_db.insert_or_update_service(
            service_date="2026-02-22",
            service_name="Morning Worship",
            source_file="file3.pptx",
            source_hash="hash3",
        )

        # Query for middle service
        results = temp_db.query_services("2026-02-10", "2026-02-20")
        assert len(results) == 1
        assert results[0]["service_date"] == "2026-02-15"

    def test_query_copy_events_by_date_range(self, temp_db):
        """Query copy events by date range."""
        # Set up two services with songs
        service_id_1 = temp_db.insert_or_update_service(
            service_date="2026-02-15",
            service_name="Morning Worship",
            source_file="file1.pptx",
            source_hash="hash1",
        )

        service_id_2 = temp_db.insert_or_update_service(
            service_date="2026-02-22",
            service_name="Morning Worship",
            source_file="file2.pptx",
            source_hash="hash2",
        )

        song_id = temp_db.insert_or_get_song("majesty", "Majesty")

        # Create copy events for both services
        temp_db.insert_copy_event(
            service_id=service_id_1,
            song_id=song_id,
            reproduction_type="projection",
            count=1,
            reportable=True,
        )

        temp_db.insert_copy_event(
            service_id=service_id_2,
            song_id=song_id,
            reproduction_type="projection",
            count=1,
            reportable=True,
        )

        # Query for second service only
        results = temp_db.query_copy_events("2026-02-20", "2026-02-28")
        assert len(results) == 1
        assert results[0]["service_date"] == "2026-02-22"

    def test_query_services_by_leader_exact(self, temp_db):
        """Filter services by song leader (exact name)."""
        temp_db.insert_or_update_service(
            service_date="2026-02-15",
            service_name="Morning Worship",
            source_file="file1.pptx",
            source_hash="hash1",
            song_leader="Matt Shirel",
        )
        temp_db.insert_or_update_service(
            service_date="2026-02-22",
            service_name="Morning Worship",
            source_file="file2.pptx",
            source_hash="hash2",
            song_leader="John Smith",
        )

        results = temp_db.query_services("2026-01-01", "2026-12-31", song_leader="Matt Shirel")
        assert len(results) == 1
        assert results[0]["song_leader"] == "Matt Shirel"

    def test_query_services_by_leader_partial(self, temp_db):
        """Filter services by song leader (partial, case-insensitive)."""
        temp_db.insert_or_update_service(
            service_date="2026-02-15",
            service_name="Morning Worship",
            source_file="file1.pptx",
            source_hash="hash1",
            song_leader="Matthew Shirel",
        )
        temp_db.insert_or_update_service(
            service_date="2026-02-22",
            service_name="Evening Worship",
            source_file="file2.pptx",
            source_hash="hash2",
            song_leader="John Smith",
        )

        results = temp_db.query_services("2026-01-01", "2026-12-31", song_leader="matt")
        assert len(results) == 1
        assert "Matthew" in results[0]["song_leader"]

    def test_query_services_no_leader_filter(self, temp_db):
        """query_services without leader returns all services."""
        for i, leader in enumerate(["Alice", "Bob", "Carol"]):
            temp_db.insert_or_update_service(
                service_date=f"2026-02-{15 + i:02d}",
                service_name="Morning Worship",
                source_file=f"file{i}.pptx",
                source_hash=f"hash{i}",
                song_leader=leader,
            )

        results = temp_db.query_services("2026-01-01", "2026-12-31")
        assert len(results) == 3

    def test_query_copy_events_by_service_ids(self, temp_db):
        """Filter copy events to specific service IDs."""
        service_id_1 = temp_db.insert_or_update_service(
            service_date="2026-02-15",
            service_name="Morning Worship",
            source_file="file1.pptx",
            source_hash="hash1",
        )
        service_id_2 = temp_db.insert_or_update_service(
            service_date="2026-02-22",
            service_name="Morning Worship",
            source_file="file2.pptx",
            source_hash="hash2",
        )

        song_id = temp_db.insert_or_get_song("majesty", "Majesty")

        temp_db.insert_copy_event(service_id=service_id_1, song_id=song_id, reproduction_type="projection", reportable=True)
        temp_db.insert_copy_event(service_id=service_id_2, song_id=song_id, reproduction_type="projection", reportable=True)

        # Restrict to service_id_1 only
        results = temp_db.query_copy_events("2026-01-01", "2026-12-31", service_ids=[service_id_1])
        assert len(results) == 1
        assert results[0]["service_id"] == service_id_1


@pytest.mark.integration
class TestMissingCredits:
    """Tests for query_songs_missing_credits and update_song_edition_credits."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()
            yield db
            db.close()

    def _setup_song_in_service(self, db, canonical, display, source_file="test.pptx", edition_id=None):
        """Helper: create a service+song+service_song and optional copy_event."""
        service_id = db.insert_or_update_service(
            service_date="2026-02-15",
            service_name="Morning Worship",
            source_file=source_file,
            source_hash=f"hash-{canonical}",
        )
        song_id = db.insert_or_get_song(canonical, display)
        db.insert_service_song(service_id=service_id, song_id=song_id, ordinal=1, song_edition_id=edition_id)
        return service_id, song_id

    def test_query_songs_missing_credits_no_edition(self, temp_db):
        """Songs with no edition row appear in missing credits query."""
        self._setup_song_in_service(temp_db, "amazing grace", "Amazing Grace")

        missing = temp_db.query_songs_missing_credits()
        titles = [r["display_title"] for r in missing]
        assert "Amazing Grace" in titles

    def test_query_songs_missing_credits_null_credits_edition(self, temp_db):
        """Songs with edition but all-NULL credits appear in missing query."""
        song_id = temp_db.insert_or_get_song("holy holy holy", "Holy Holy Holy")
        edition_id = temp_db.insert_or_get_song_edition(song_id=song_id)  # no credits
        service_id = temp_db.insert_or_update_service(
            service_date="2026-02-15", service_name="Morning Worship",
            source_file="test.pptx", source_hash="hash-hhh"
        )
        temp_db.insert_service_song(service_id=service_id, song_id=song_id, ordinal=1, song_edition_id=edition_id)

        missing = temp_db.query_songs_missing_credits()
        titles = [r["display_title"] for r in missing]
        assert "Holy Holy Holy" in titles

    def test_query_songs_with_credits_excluded(self, temp_db):
        """Songs with credits do NOT appear in missing query."""
        song_id = temp_db.insert_or_get_song("majesty", "Majesty")
        edition_id = temp_db.insert_or_get_song_edition(
            song_id=song_id, words_by="Jack Hayford"
        )
        service_id = temp_db.insert_or_update_service(
            service_date="2026-02-15", service_name="Morning Worship",
            source_file="test.pptx", source_hash="hash-maj"
        )
        temp_db.insert_service_song(service_id=service_id, song_id=song_id, ordinal=1, song_edition_id=edition_id)

        missing = temp_db.query_songs_missing_credits()
        titles = [r["display_title"] for r in missing]
        assert "Majesty" not in titles

    def test_update_song_edition_credits_updates_existing(self, temp_db):
        """update_song_edition_credits updates a NULL-credit edition row."""
        song_id = temp_db.insert_or_get_song("amazing grace", "Amazing Grace")
        # Insert edition with no credits
        temp_db.insert_or_get_song_edition(song_id=song_id)

        temp_db.update_song_edition_credits(song_id, words_by="John Newton")

        cursor = temp_db.conn.cursor()
        cursor.execute("SELECT words_by FROM song_editions WHERE song_id = ?", (song_id,))
        row = cursor.fetchone()
        assert row[0] == "John Newton"

    def test_update_song_edition_credits_inserts_when_missing(self, temp_db):
        """update_song_edition_credits inserts edition row when none exists."""
        song_id = temp_db.insert_or_get_song("o worship the king", "O Worship The King")
        # No edition row exists

        temp_db.update_song_edition_credits(song_id, words_by="Robert Grant", music_by="Johann Haydn")

        cursor = temp_db.conn.cursor()
        cursor.execute("SELECT words_by, music_by FROM song_editions WHERE song_id = ?", (song_id,))
        row = cursor.fetchone()
        assert row[0] == "Robert Grant"
        assert row[1] == "Johann Haydn"

    def test_update_song_edition_credits_backfills_copy_events(self, temp_db):
        """update_song_edition_credits backfills NULL song_edition_id in copy_events."""
        song_id = temp_db.insert_or_get_song("a common love", "A Common Love")
        service_id = temp_db.insert_or_update_service(
            service_date="2026-02-15", service_name="Morning Worship",
            source_file="test.pptx", source_hash="hash-acl"
        )
        # Insert copy event with NULL edition
        temp_db.insert_copy_event(
            service_id=service_id, song_id=song_id,
            reproduction_type="projection", reportable=True
        )

        # Now repair credits
        temp_db.update_song_edition_credits(song_id, words_by="Bob Gillman")

        # copy_events should now have the edition_id backfilled
        cursor = temp_db.conn.cursor()
        cursor.execute("SELECT song_edition_id FROM copy_events WHERE song_id = ?", (song_id,))
        row = cursor.fetchone()
        assert row[0] is not None

    def test_update_song_edition_credits_backfills_service_songs(self, temp_db):
        """update_song_edition_credits backfills NULL song_edition_id in service_songs."""
        song_id = temp_db.insert_or_get_song("a common love", "A Common Love")
        service_id = temp_db.insert_or_update_service(
            service_date="2026-02-15", service_name="Morning Worship",
            source_file="test.pptx", source_hash="hash-acl2"
        )
        temp_db.insert_service_song(service_id=service_id, song_id=song_id, ordinal=1)

        temp_db.update_song_edition_credits(song_id, words_by="Bob Gillman")

        cursor = temp_db.conn.cursor()
        cursor.execute("SELECT song_edition_id FROM service_songs WHERE song_id = ?", (song_id,))
        row = cursor.fetchone()
        assert row[0] is not None


@pytest.mark.integration
class TestLeaderTopSongs:
    """Tests for query_leader_top_songs and query_leader_service_count."""

    @pytest.fixture
    def db_with_leader_data(self, tmp_path):
        """DB with Matt leading 3 services:
        - Amazing Grace: 2 services
        - How Great Thou Art: 1 service
        """
        db_path = tmp_path / "leader_test.db"
        db = Database(db_path)
        db.connect()
        db.init_schema()

        song1 = db.insert_or_get_song("amazing grace", "Amazing Grace")
        song2 = db.insert_or_get_song("how great thou art", "How Great Thou Art")

        for i, (song_id, date) in enumerate([
            (song1, "2026-01-01"),
            (song1, "2026-01-08"),
            (song2, "2026-01-15"),
        ]):
            svc_id = db.insert_or_update_service(
                service_date=date,
                service_name="AM Worship",
                source_file=f"file{i}.pptx",
                source_hash=f"hash{i}",
                song_leader="Matt",
            )
            db.insert_service_song(svc_id, song_id, ordinal=1)

        db.close()
        return db_path

    def test_top_songs_includes_repeated_song(self, db_with_leader_data):
        db = Database(db_with_leader_data)
        db.connect()
        results = db.query_leader_top_songs("Matt")
        db.close()
        titles = [r["display_title"] for r in results]
        assert "Amazing Grace" in titles

    def test_top_songs_excludes_one_off_song(self, db_with_leader_data):
        db = Database(db_with_leader_data)
        db.connect()
        results = db.query_leader_top_songs("Matt")
        db.close()
        titles = [r["display_title"] for r in results]
        assert "How Great Thou Art" not in titles

    def test_top_songs_min_count_1_includes_all(self, db_with_leader_data):
        db = Database(db_with_leader_data)
        db.connect()
        results = db.query_leader_top_songs("Matt", min_count=1)
        db.close()
        titles = [r["display_title"] for r in results]
        assert "Amazing Grace" in titles
        assert "How Great Thou Art" in titles

    def test_top_songs_ordered_by_count_desc(self, db_with_leader_data):
        db = Database(db_with_leader_data)
        db.connect()
        results = db.query_leader_top_songs("Matt", min_count=1)
        db.close()
        counts = [r["performance_count"] for r in results]
        assert counts == sorted(counts, reverse=True)

    def test_service_count_correct(self, db_with_leader_data):
        db = Database(db_with_leader_data)
        db.connect()
        count = db.query_leader_service_count("Matt")
        db.close()
        assert count == 3

    def test_service_count_zero_for_unknown_leader(self, db_with_leader_data):
        db = Database(db_with_leader_data)
        db.connect()
        count = db.query_leader_service_count("Nobody")
        db.close()
        assert count == 0


@pytest.mark.integration
class TestTransactionBoundary:
    """Tests for Database.transaction() context manager (#14)."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        db = Database(tmp_path / "txn_test.db")
        db.connect()
        db.init_schema()
        yield db
        db.close()

    def test_transaction_commits_on_success(self, temp_db):
        """All inserts inside transaction() are visible after the block exits normally."""
        with temp_db.transaction():
            song_id = temp_db.insert_or_get_song("amazing grace", "Amazing Grace")
            temp_db.insert_or_get_song("holy holy holy", "Holy Holy Holy")

        cursor = temp_db.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM songs")
        assert cursor.fetchone()[0] == 2

    def test_transaction_rolls_back_on_exception(self, temp_db):
        """If an exception is raised inside transaction(), no changes are persisted."""
        with pytest.raises(ValueError):
            with temp_db.transaction():
                temp_db.insert_or_get_song("amazing grace", "Amazing Grace")
                raise ValueError("simulated failure mid-import")

        cursor = temp_db.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM songs")
        assert cursor.fetchone()[0] == 0

    def test_transaction_restores_pre_import_state(self, temp_db):
        """A failed import inside transaction() leaves the DB exactly as it was before."""
        # Pre-existing data
        temp_db.insert_or_get_song("pre-existing song", "Pre-Existing Song")

        with pytest.raises(RuntimeError):
            with temp_db.transaction():
                temp_db.insert_or_get_song("new song", "New Song")
                raise RuntimeError("import error")

        cursor = temp_db.conn.cursor()
        cursor.execute("SELECT canonical_title FROM songs ORDER BY id")
        rows = [r[0] for r in cursor.fetchall()]
        assert rows == ["pre-existing song"]

    def test_nested_individual_commits_outside_transaction(self, temp_db):
        """Without transaction(), each DB call commits independently."""
        temp_db.insert_or_get_song("song one", "Song One")
        temp_db.insert_or_get_song("song two", "Song Two")

        cursor = temp_db.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM songs")
        assert cursor.fetchone()[0] == 2

    def test_transaction_exception_is_reraised(self, temp_db):
        """The exception that caused rollback is propagated to the caller."""
        with pytest.raises(KeyError, match="test-key"):
            with temp_db.transaction():
                raise KeyError("test-key")


@pytest.mark.integration
class TestDatabaseConnect:
    """Tests for Database.connect() pragma configuration."""

    @pytest.fixture
    def db(self, tmp_path):
        db = Database(tmp_path / "pragma_test.db")
        db.connect()
        db.init_schema()
        yield db
        db.close()

    @pytest.mark.integration
    def test_wal_mode_enabled(self, db):
        cursor = db.conn.cursor()
        cursor.execute("PRAGMA journal_mode")
        row = cursor.fetchone()
        assert row[0] == "wal"

    @pytest.mark.integration
    def test_foreign_keys_enabled(self, db):
        cursor = db.conn.cursor()
        cursor.execute("PRAGMA foreign_keys")
        row = cursor.fetchone()
        assert row[0] == 1


@pytest.mark.integration
class TestServiceCleanup:
    """Tests for service data cleanup."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()
            yield db
            db.close()

    def test_delete_service_data(self, temp_db):
        """Delete all data for a service."""
        service_id = temp_db.insert_or_update_service(
            service_date="2026-02-15",
            service_name="Morning Worship",
            source_file="file.pptx",
            source_hash="hash1",
        )

        song_id = temp_db.insert_or_get_song("majesty", "Majesty")

        # Add service song and copy events
        temp_db.insert_service_song(
            service_id=service_id,
            song_id=song_id,
            ordinal=1,
        )

        temp_db.insert_copy_event(
            service_id=service_id,
            song_id=song_id,
            reproduction_type="projection",
        )

        # Verify data was created
        cursor = temp_db.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM services")
        assert cursor.fetchone()[0] == 1

        # Delete service data
        temp_db.delete_service_data(service_id)

        # Verify service is deleted
        cursor.execute("SELECT COUNT(*) FROM services WHERE id = ?", (service_id,))
        assert cursor.fetchone()[0] == 0

        # Verify service songs are deleted
        cursor.execute("SELECT COUNT(*) FROM service_songs WHERE service_id = ?", (service_id,))
        assert cursor.fetchone()[0] == 0

        # Verify copy events are deleted
        cursor.execute("SELECT COUNT(*) FROM copy_events WHERE service_id = ?", (service_id,))
        assert cursor.fetchone()[0] == 0

        # Song should still exist (not deleted)
        cursor.execute("SELECT COUNT(*) FROM songs WHERE id = ?", (song_id,))
        assert cursor.fetchone()[0] == 1


@pytest.mark.integration
class TestSchemaVersioning:
    """Tests for schema version detection and enforcement (#19)."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        db = Database(tmp_path / "schema_test.db")
        db.connect()
        db.init_schema()
        yield db
        db.close()

    def test_init_schema_sets_user_version(self, temp_db):
        """init_schema() sets PRAGMA user_version to _SCHEMA_VERSION."""
        from worship_catalog.db import _SCHEMA_VERSION

        cursor = temp_db.conn.cursor()
        cursor.execute("PRAGMA user_version")
        version = cursor.fetchone()[0]
        assert version == _SCHEMA_VERSION
        assert _SCHEMA_VERSION >= 1

    def test_fresh_db_version_matches_expected(self, tmp_path):
        """A fresh DB after init_schema has the expected schema version."""
        from worship_catalog.db import _SCHEMA_VERSION

        db = Database(tmp_path / "fresh.db")
        db.connect()
        db.init_schema()
        cursor = db.conn.cursor()
        cursor.execute("PRAGMA user_version")
        assert cursor.fetchone()[0] == _SCHEMA_VERSION
        db.close()

    def test_connect_raises_on_newer_schema_version(self, tmp_path):
        """Connecting to a DB with a newer schema version raises SchemaVersionError."""
        from worship_catalog.db import SchemaVersionError, _SCHEMA_VERSION

        db_path = tmp_path / "newer.db"
        # Create a DB with a higher schema version than we support
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION + 10}")
        conn.close()

        db = Database(db_path)
        with pytest.raises(SchemaVersionError):
            db.connect()

    def test_schema_version_constant_is_positive(self):
        """_SCHEMA_VERSION must be a positive integer."""
        from worship_catalog.db import _SCHEMA_VERSION
        assert isinstance(_SCHEMA_VERSION, int)
        assert _SCHEMA_VERSION >= 1


class TestStreamCopyEvents:
    """iter_copy_events() yields rows without loading all into memory (#27)."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        from worship_catalog.db import Database
        db = Database(tmp_path / "stream_test.db")
        db.connect()
        db.init_schema()
        yield db
        db.close()

    def test_iter_copy_events_returns_generator(self, temp_db):
        import types
        result = temp_db.iter_copy_events("0000-01-01", "9999-12-31")
        assert isinstance(result, types.GeneratorType)

    def test_iter_copy_events_yields_same_data_as_query(self, temp_db):
        svc_id = temp_db.insert_or_update_service(
            service_date="2026-01-01", service_name="Sunday AM",
            source_file="test.pptx", source_hash="hash1",
            song_leader=None, preacher=None, sermon_title=None,
        )
        song_id = temp_db.insert_or_get_song("amazing grace", "Amazing Grace")
        temp_db.insert_or_get_copy_event(service_id=svc_id, song_id=song_id,
                                          song_edition_id=None, reproduction_type="projection",
                                          count=1, reportable=True)
        streamed = list(temp_db.iter_copy_events("0000-01-01", "9999-12-31"))
        queried = temp_db.query_copy_events("0000-01-01", "9999-12-31")
        assert len(streamed) == len(queried)
        assert streamed[0]["display_title"] == queried[0]["display_title"]

    def test_iter_copy_events_empty_db_yields_nothing(self, temp_db):
        result = list(temp_db.iter_copy_events("0000-01-01", "9999-12-31"))
        assert result == []


# ---------------------------------------------------------------------------
# #111: Stats report must count unique (service_id, song_id) appearances,
#       not raw copy_event rows  (issue #97)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStatsReportCountsUniqueServiceSongPairs:
    """Issue #97 — stats report double-counts songs when a song has multiple
    copy events per service (e.g., bulletin + projection).

    The report should count how many distinct services a song was sung in,
    not the number of copy_event rows associated with that song.
    """

    @pytest.fixture
    def temp_db(self):
        with TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "stats_test.db")
            db.connect()
            db.init_schema()
            yield db
            db.close()

    def test_song_with_two_copy_events_counts_as_one(self, temp_db):
        """A song performed once (one service) but with TWO copy events must appear
        with count=1, not count=2."""
        from worship_catalog.services.report_service import compute_stats_data

        song_id = temp_db.insert_or_get_song("amazing grace", "Amazing Grace")
        edition_id = temp_db.insert_or_get_song_edition(song_id, words_by="John Newton")

        service_id = temp_db.insert_or_update_service(
            service_date="2026-01-04",
            service_name="AM Worship",
            source_file="test.pptx",
            source_hash="abc999",
            song_leader="Alice",
        )
        temp_db.insert_service_song(service_id, song_id, ordinal=1, song_edition_id=edition_id)

        # Two copy events for the same song in the same service
        temp_db.insert_or_get_copy_event(
            service_id, song_id, "projection", song_edition_id=edition_id
        )
        temp_db.insert_or_get_copy_event(
            service_id, song_id, "bulletin", song_edition_id=edition_id
        )

        data = compute_stats_data(
            temp_db, "2026-01-01", "2026-12-31", leader=None, all_songs=True
        )

        song_counts = dict(data["sorted_songs"])
        assert "Amazing Grace" in song_counts, (
            "Amazing Grace should appear in the stats report"
        )
        assert song_counts["Amazing Grace"] == 1, (
            f"Expected count=1 (one service) but got {song_counts['Amazing Grace']}; "
            "stats report is double-counting copy events instead of counting distinct services"
        )

    def test_song_sung_in_two_services_counts_as_two(self, temp_db):
        """A song performed in two different services must still count as 2."""
        from worship_catalog.services.report_service import compute_stats_data

        song_id = temp_db.insert_or_get_song("how great thou art", "How Great Thou Art")
        edition_id = temp_db.insert_or_get_song_edition(song_id, words_by="Stuart K. Hine")

        for i, (date, name, hash_) in enumerate([
            ("2026-01-04", "AM Worship", "h1"),
            ("2026-01-11", "AM Worship", "h2"),
        ]):
            svc_id = temp_db.insert_or_update_service(
                service_date=date,
                service_name=name,
                source_file=f"f{i}.pptx",
                source_hash=hash_,
                song_leader="Alice",
            )
            temp_db.insert_service_song(svc_id, song_id, ordinal=1, song_edition_id=edition_id)
            # Each service has two copy events
            temp_db.insert_or_get_copy_event(svc_id, song_id, "projection", song_edition_id=edition_id)
            temp_db.insert_or_get_copy_event(svc_id, song_id, "bulletin", song_edition_id=edition_id)

        data = compute_stats_data(
            temp_db, "2026-01-01", "2026-12-31", leader=None, all_songs=True
        )

        song_counts = dict(data["sorted_songs"])
        assert song_counts.get("How Great Thou Art") == 2, (
            f"Expected count=2 (two services) but got {song_counts.get('How Great Thou Art')}; "
            "each service should count once regardless of copy event count"
        )

    def test_two_songs_each_with_two_copy_events_counts_each_as_one(self, temp_db):
        """Two different songs, each with two copy events in one service, both count=1."""
        from worship_catalog.services.report_service import compute_stats_data

        song1_id = temp_db.insert_or_get_song("song one", "Song One")
        song2_id = temp_db.insert_or_get_song("song two", "Song Two")
        ed1 = temp_db.insert_or_get_song_edition(song1_id, words_by="Author A")
        ed2 = temp_db.insert_or_get_song_edition(song2_id, words_by="Author B")

        service_id = temp_db.insert_or_update_service(
            service_date="2026-01-04",
            service_name="AM Worship",
            source_file="test.pptx",
            source_hash="xyz123",
            song_leader="Bob",
        )
        temp_db.insert_service_song(service_id, song1_id, ordinal=1, song_edition_id=ed1)
        temp_db.insert_service_song(service_id, song2_id, ordinal=2, song_edition_id=ed2)
        for rt in ("projection", "bulletin"):
            temp_db.insert_or_get_copy_event(service_id, song1_id, rt, song_edition_id=ed1)
            temp_db.insert_or_get_copy_event(service_id, song2_id, rt, song_edition_id=ed2)

        data = compute_stats_data(
            temp_db, "2026-01-01", "2026-12-31", leader=None, all_songs=True
        )

        song_counts = dict(data["sorted_songs"])
        assert song_counts.get("Song One") == 1, (
            f"Song One expected count=1 but got {song_counts.get('Song One')}"
        )
        assert song_counts.get("Song Two") == 1, (
            f"Song Two expected count=1 but got {song_counts.get('Song Two')}"
        )


# ---------------------------------------------------------------------------
# _safe_order_by helper (#75)
# ---------------------------------------------------------------------------


class TestSafeOrderBy:
    """_safe_order_by must whitelist valid columns and reject injection attempts."""

    def test_valid_column_returns_col(self):
        from worship_catalog.db import _safe_order_by
        assert _safe_order_by("title", frozenset({"title", "date"})) == "title"

    def test_another_valid_column_returns_col(self):
        from worship_catalog.db import _safe_order_by
        assert _safe_order_by("date", frozenset({"title", "date"})) == "date"

    def test_invalid_column_raises_value_error(self):
        from worship_catalog.db import _safe_order_by
        with pytest.raises(ValueError, match="Invalid sort column"):
            _safe_order_by("'; DROP TABLE songs; --", frozenset({"title"}))

    def test_empty_col_raises(self):
        from worship_catalog.db import _safe_order_by
        with pytest.raises(ValueError):
            _safe_order_by("", frozenset({"title"}))

    def test_whitespace_only_col_raises(self):
        from worship_catalog.db import _safe_order_by
        with pytest.raises(ValueError):
            _safe_order_by("   ", frozenset({"title"}))

    def test_sql_injection_attempt_raises(self):
        from worship_catalog.db import _safe_order_by
        with pytest.raises(ValueError, match="Invalid sort column"):
            _safe_order_by("1; DROP TABLE songs", frozenset({"title", "date"}))


# ---------------------------------------------------------------------------
# Database connection lifecycle (#95)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDatabaseConnectionLifecycle:
    """Connection management edge cases (#95)."""

    def test_double_connect_is_safe(self, tmp_path: Path) -> None:
        """Calling connect() twice must not raise."""
        db_path = tmp_path / "lifecycle.db"
        db = Database(db_path)
        db.connect()
        db.connect()  # second call — must not raise
        db.close()

    def test_operations_after_close_raise(self, tmp_path: Path) -> None:
        """Calling a query method on a closed db must raise a clear error."""
        db_path = tmp_path / "lifecycle2.db"
        db = Database(db_path)
        db.connect()
        db.init_schema()
        db.close()
        # After close, conn is still set but the underlying sqlite connection is
        # closed, so any cursor() call must raise (not silently fail).
        with pytest.raises(Exception):
            db.insert_or_get_song("test title", "Test Title")


# ---------------------------------------------------------------------------
# Issue #100 — update_import_job must not build SQL via f-string with
# user-controlled field names.
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestUpdateImportJobSQLSafety:
    """Whitelist validation on update_import_job fields — issue #100."""

    @pytest.fixture
    def temp_db(self, tmp_path: Path) -> Database:
        db = Database(tmp_path / "test.db")
        db.connect()
        db.init_schema()
        return db

    def test_update_with_valid_status_succeeds(self, temp_db: Database) -> None:
        job_id = "valid-job-001"
        temp_db.create_import_job(job_id, filename="test.pptx")
        temp_db.update_import_job(job_id, status="running")
        row = temp_db.get_import_job(job_id)
        assert row is not None
        assert row["status"] == "running"
        temp_db.close()

    def test_update_with_valid_songs_imported_succeeds(self, temp_db: Database) -> None:
        job_id = "valid-job-002"
        temp_db.create_import_job(job_id, filename="test.pptx")
        temp_db.update_import_job(job_id, songs_imported=5)
        row = temp_db.get_import_job(job_id)
        assert row is not None
        assert row["songs_imported"] == 5
        temp_db.close()

    def test_update_with_unknown_field_raises_value_error(self, tmp_path: Path) -> None:
        db = Database(tmp_path / "test2.db")
        db.connect()
        db.init_schema()
        job_id = "evil-job-001"
        db.create_import_job(job_id, filename="test.pptx")
        with pytest.raises(ValueError, match="(?i)unknown field"):
            db.update_import_job(job_id, **{"'; DROP TABLE import_jobs; --": "evil"})  # type: ignore[arg-type]
        db.close()


# ---------------------------------------------------------------------------
# Issue #98 — all timestamps must be UTC-aware ISO strings.
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTimestampConsistency:
    """Timestamps produced by db methods must be timezone-aware UTC — issue #98."""

    @pytest.fixture
    def temp_db(self, tmp_path: Path) -> Database:
        db = Database(tmp_path / "ts_test.db")
        db.connect()
        db.init_schema()
        return db

    def test_import_job_started_at_is_utc_aware(self, temp_db: Database) -> None:
        from datetime import datetime, timezone

        job_id = "ts-job-001"
        temp_db.create_import_job(job_id, filename="test.pptx")
        row = temp_db.get_import_job(job_id)
        temp_db.close()
        assert row is not None
        ts = datetime.fromisoformat(row["started_at"])
        assert ts.tzinfo is not None, (
            f"started_at '{row['started_at']}' must be timezone-aware"
        )

    def test_import_job_completed_at_is_utc_aware_when_set(self, temp_db: Database) -> None:
        from datetime import datetime, timezone

        job_id = "ts-job-002"
        temp_db.create_import_job(job_id, filename="test.pptx")
        temp_db.update_import_job(job_id, status="complete")
        row = temp_db.get_import_job(job_id)
        temp_db.close()
        assert row is not None
        assert row["completed_at"] is not None, "completed_at must be set for 'complete' status"
        ts = datetime.fromisoformat(row["completed_at"])
        assert ts.tzinfo is not None, (
            f"completed_at '{row['completed_at']}' must be timezone-aware"
        )

    def test_insert_or_update_service_imported_at_is_utc_aware(
        self, temp_db: Database
    ) -> None:
        from datetime import datetime, timezone

        temp_db.insert_or_update_service(
            service_date="2026-01-01",
            service_name="AM Worship",
            source_file="file.pptx",
            source_hash="abc",
        )
        rows = temp_db.query_services("2026-01-01", "2026-01-01")
        temp_db.close()
        assert rows, "Service should have been inserted"
        ts = datetime.fromisoformat(rows[0]["imported_at"])
        assert ts.tzinfo is not None, (
            f"imported_at '{rows[0]['imported_at']}' must be timezone-aware"
        )

    def test_timestamps_round_trip_correctly(self, temp_db: Database) -> None:
        """Timestamps stored in SQLite round-trip back as the same timezone-aware value — issue #98."""
        from datetime import datetime, timezone

        job_id = "ts-roundtrip-001"
        before = datetime.now(timezone.utc)
        temp_db.create_import_job(job_id, filename="roundtrip.pptx")
        temp_db.update_import_job(job_id, status="complete")
        row = temp_db.get_import_job(job_id)
        after = datetime.now(timezone.utc)
        temp_db.close()

        assert row is not None
        started = datetime.fromisoformat(row["started_at"])
        completed = datetime.fromisoformat(row["completed_at"])

        # Both must be timezone-aware and fall within the test window
        assert started.tzinfo is not None
        assert completed.tzinfo is not None
        assert before <= started <= after, (
            f"started_at {started} not within [{before}, {after}]"
        )
        assert before <= completed <= after, (
            f"completed_at {completed} not within [{before}, {after}]"
        )


# ---------------------------------------------------------------------------
# Issue #56 — insert_copy_event() must emit DeprecationWarning.
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestInsertCopyEventDeprecation:
    """insert_copy_event() must warn callers to use insert_or_get_copy_event() — issue #56."""

    @pytest.fixture
    def temp_db(self, tmp_path: Path) -> Database:
        db = Database(tmp_path / "dep_test.db")
        db.connect()
        db.init_schema()
        return db

    def test_insert_copy_event_emits_deprecation_warning(self, temp_db: Database) -> None:
        import warnings

        service_id = temp_db.insert_or_update_service(
            service_date="2026-01-01",
            service_name="AM Worship",
            source_file="file.pptx",
            source_hash="dep-hash",
        )
        song_id = temp_db.insert_or_get_song("amazing grace", "Amazing Grace")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            temp_db.insert_copy_event(
                service_id=service_id,
                song_id=song_id,
                reproduction_type="projection",
            )
        temp_db.close()

        assert any(
            issubclass(warning.category, DeprecationWarning) for warning in w
        ), f"Expected DeprecationWarning, got: {[str(warning.category) for warning in w]}"

    def test_insert_copy_event_still_inserts_row(self, temp_db: Database) -> None:
        """Despite the deprecation, the insert must still succeed."""
        import warnings

        service_id = temp_db.insert_or_update_service(
            service_date="2026-01-02",
            service_name="AM Worship",
            source_file="file2.pptx",
            source_hash="dep-hash2",
        )
        song_id = temp_db.insert_or_get_song("how great thou art", "How Great Thou Art")

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            event_id = temp_db.insert_copy_event(
                service_id=service_id,
                song_id=song_id,
                reproduction_type="projection",
            )
        temp_db.close()

        assert event_id > 0


# ---------------------------------------------------------------------------
# Issue #133 — Database.close() must null self.conn
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDatabaseCloseNullsConn:
    """After close(), self.conn must be None and subsequent calls must raise — issue #133."""

    @pytest.fixture
    def temp_db(self, tmp_path: Path) -> Database:
        db = Database(tmp_path / "close_test.db")
        db.connect()
        db.init_schema()
        return db

    def test_conn_is_none_after_close(self, temp_db: Database) -> None:
        """After close(), self.conn must be None."""
        temp_db.close()
        assert temp_db.conn is None, (
            f"Expected conn=None after close(), got {temp_db.conn!r}"
        )

    def test_query_after_close_raises(self, temp_db: Database) -> None:
        """Attempting a query after close() must raise (not silently operate on closed conn)."""
        temp_db.close()
        with pytest.raises((AssertionError, Exception)):
            temp_db.cursor()

    def test_close_is_idempotent(self, temp_db: Database) -> None:
        """Calling close() twice must not raise any error."""
        temp_db.close()
        # Second close should be safe
        temp_db.close()  # Must not raise

    def test_close_then_connect_works(self, temp_db: Database, tmp_path: Path) -> None:
        """After close(), a fresh connect() works (conn becomes non-None again)."""
        db_path = temp_db.db_path
        temp_db.close()
        assert temp_db.conn is None
        temp_db.connect()
        assert temp_db.conn is not None
        temp_db.close()


# ---------------------------------------------------------------------------
# Issue #143 — purge_old_import_jobs() untested
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPurgeOldImportJobs:
    """purge_old_import_jobs() correctness tests — issue #143."""

    @pytest.fixture
    def temp_db(self, tmp_path: Path) -> Database:
        db = Database(tmp_path / "purge_test.db")
        db.connect()
        db.init_schema()
        return db

    def _insert_jobs(self, db: Database, count: int) -> list[str]:
        """Insert *count* jobs with sequentially older started_at timestamps."""
        from datetime import datetime, timezone, timedelta
        ids = []
        for i in range(count):
            job_id = f"purge-job-{i:04d}"
            # Oldest jobs have largest i (furthest in the past)
            started_at = (
                datetime.now(timezone.utc) - timedelta(days=count - i)
            ).isoformat()
            db.create_import_job(job_id, filename=f"job{i}.pptx", started_at=started_at)
            ids.append(job_id)
        return ids

    def test_purge_keeps_correct_number_of_jobs(self, temp_db: Database) -> None:
        """After purge_old_import_jobs(keep=10), exactly 10 jobs remain."""
        self._insert_jobs(temp_db, 15)
        temp_db.purge_old_import_jobs(keep=10)
        remaining = temp_db.list_import_jobs()
        temp_db.close()
        assert len(remaining) == 10, (
            f"Expected 10 jobs after purge(keep=10), got {len(remaining)}"
        )

    def test_purge_keeps_newest_jobs(self, temp_db: Database) -> None:
        """purge_old_import_jobs(keep=10) must keep the 10 NEWEST jobs."""
        ids = self._insert_jobs(temp_db, 15)
        # ids[0..4] are oldest (most days ago), ids[10..14] are newest
        temp_db.purge_old_import_jobs(keep=10)
        remaining = temp_db.list_import_jobs()
        remaining_ids = {r["job_id"] for r in remaining}
        temp_db.close()
        # The 5 oldest must be gone
        for old_id in ids[:5]:
            assert old_id not in remaining_ids, (
                f"Oldest job {old_id!r} should have been deleted but was kept"
            )
        # The 10 newest must survive
        for new_id in ids[5:]:
            assert new_id in remaining_ids, (
                f"Newest job {new_id!r} should be kept but was deleted"
            )

    def test_purge_keep_zero_deletes_all(self, temp_db: Database) -> None:
        """purge_old_import_jobs(keep=0) must delete ALL jobs."""
        self._insert_jobs(temp_db, 5)
        temp_db.purge_old_import_jobs(keep=0)
        remaining = temp_db.list_import_jobs()
        temp_db.close()
        assert remaining == [], f"Expected no jobs after purge(keep=0), got {remaining}"

    def test_purge_on_empty_table_does_not_error(self, temp_db: Database) -> None:
        """purge_old_import_jobs on an empty table must not raise."""
        temp_db.purge_old_import_jobs(keep=10)  # Must not raise
        remaining = temp_db.list_import_jobs()
        temp_db.close()
        assert remaining == []


# ---------------------------------------------------------------------------
# Issue #144 — SchemaVersionError guard tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSchemaVersionErrorGuard:
    """SchemaVersionError guard comprehensive tests — issue #144."""

    def test_correct_schema_version_no_error(self, tmp_path: Path) -> None:
        """Opening a DB with the correct schema version raises no error."""
        from worship_catalog.db import _SCHEMA_VERSION
        db = Database(tmp_path / "correct_version.db")
        db.connect()
        db.init_schema()
        # Re-open with correct version — must not raise
        db.close()
        db2 = Database(tmp_path / "correct_version.db")
        db2.connect()  # Must not raise
        db2.close()

    def test_wrong_version_raises_schema_version_error(self, tmp_path: Path) -> None:
        """Opening a DB with a NEWER schema version raises SchemaVersionError."""
        import sqlite3
        from worship_catalog.db import SchemaVersionError, _SCHEMA_VERSION
        db_path = tmp_path / "wrong_version.db"
        conn = sqlite3.connect(db_path)
        conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION + 5}")
        conn.close()
        db = Database(db_path)
        with pytest.raises(SchemaVersionError):
            db.connect()

    def test_schema_version_error_message_contains_versions(self, tmp_path: Path) -> None:
        """SchemaVersionError message must include both expected and actual versions."""
        import sqlite3
        from worship_catalog.db import SchemaVersionError, _SCHEMA_VERSION
        db_path = tmp_path / "msg_test.db"
        newer_version = _SCHEMA_VERSION + 3
        conn = sqlite3.connect(db_path)
        conn.execute(f"PRAGMA user_version = {newer_version}")
        conn.close()
        db = Database(db_path)
        with pytest.raises(SchemaVersionError) as exc_info:
            db.connect()
        msg = str(exc_info.value)
        assert str(newer_version) in msg, (
            f"Error message must contain actual version {newer_version}, got: {msg!r}"
        )
        assert str(_SCHEMA_VERSION) in msg, (
            f"Error message must contain expected version {_SCHEMA_VERSION}, got: {msg!r}"
        )

    def test_old_schema_version_does_not_raise(self, tmp_path: Path) -> None:
        """A DB with a LOWER schema version than current code opens without error.
        (The guard only blocks NEWER versions — older ones are upgraded or accepted.)
        """
        import sqlite3
        from worship_catalog.db import _SCHEMA_VERSION
        db_path = tmp_path / "old_version.db"
        # Version 0 (unset) is older — should be fine
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA user_version = 0")
        conn.close()
        db = Database(db_path)
        db.connect()  # Must not raise
        db.close()


# ---------------------------------------------------------------------------
# Issue #130 — schema migration path
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSchemaMigration:
    """Tests for incremental schema migration — issue #130."""

    def test_old_schema_gets_new_table_on_connect(self, tmp_path: Path) -> None:
        """Connecting to a v0 database applies missing tables before any operation."""
        import sqlite3

        # Simulate a pre-import_jobs database (no import_jobs table)
        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA user_version = 0")
        conn.execute(
            "CREATE TABLE songs "
            "(id INTEGER PRIMARY KEY, canonical_title TEXT, display_title TEXT)"
        )
        conn.commit()
        conn.close()
        db = Database(db_path)
        db.connect()
        db.init_schema()
        # import_jobs table must now exist
        cursor = db.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='import_jobs'"
        )
        assert cursor.fetchone() is not None
        db.close()

    def test_future_schema_raises_schema_version_error(self, tmp_path: Path) -> None:
        """DB with version > _SCHEMA_VERSION raises SchemaVersionError."""
        import sqlite3

        from worship_catalog.db import SchemaVersionError

        db_path = tmp_path / "future.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA user_version = 999")
        conn.commit()
        conn.close()
        db = Database(db_path)
        with pytest.raises(SchemaVersionError):
            db.connect()

    def test_migrations_table_created(self, tmp_path: Path) -> None:
        """init_schema() creates a schema_migrations table."""
        db_path = tmp_path / "fresh.db"
        db = Database(db_path)
        db.connect()
        db.init_schema()
        cursor = db.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='schema_migrations'"
        )
        assert cursor.fetchone() is not None
        db.close()

    def test_migrations_are_recorded(self, tmp_path: Path) -> None:
        """Each migration that runs is recorded in schema_migrations."""
        db_path = tmp_path / "fresh.db"
        db = Database(db_path)
        db.connect()
        db.init_schema()
        cursor = db.cursor()
        cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
        versions = [row[0] for row in cursor.fetchall()]
        # At minimum, migration 1 should be recorded
        assert 1 in versions
        db.close()

    def test_migrations_are_idempotent(self, tmp_path: Path) -> None:
        """Calling init_schema() twice does not duplicate migration records."""
        db_path = tmp_path / "fresh.db"
        db = Database(db_path)
        db.connect()
        db.init_schema()
        db.init_schema()  # second call
        cursor = db.cursor()
        cursor.execute("SELECT COUNT(*) FROM schema_migrations WHERE version = 1")
        assert cursor.fetchone()[0] == 1
        db.close()

    def test_user_version_updated_after_migration(self, tmp_path: Path) -> None:
        """After migrations run, PRAGMA user_version equals _SCHEMA_VERSION."""
        import sqlite3

        from worship_catalog.db import _SCHEMA_VERSION

        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA user_version = 0")
        conn.commit()
        conn.close()
        db = Database(db_path)
        db.connect()
        db.init_schema()
        cursor = db.cursor()
        cursor.execute("PRAGMA user_version")
        assert cursor.fetchone()[0] == _SCHEMA_VERSION
        db.close()

    def test_migration_log_emitted(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Migrations emit a log message when applied."""
        import sqlite3

        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA user_version = 0")
        conn.commit()
        conn.close()
        db = Database(db_path)
        db.connect()
        with caplog.at_level(logging.INFO, logger="worship_catalog.db"):
            db.init_schema()
        assert any("migration" in r.message.lower() for r in caplog.records)
        db.close()


# ---------------------------------------------------------------------------
# Issue #56 — insert_copy_event() deprecation
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestInsertCopyEventDeprecation:
    """insert_copy_event() must emit DeprecationWarning — issue #56."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.connect()
        db.init_schema()
        # Insert prerequisite rows
        service_id = db.insert_or_update_service(
            service_date="2026-02-15",
            service_name="Morning Worship",
            source_file="test.pptx",
            source_hash="hash_deprecation",
        )
        song_id = db.insert_or_get_song("amazing grace", "Amazing Grace")
        yield db, service_id, song_id
        db.close()

    def test_insert_copy_event_emits_deprecation_warning(self, temp_db):
        """insert_copy_event() must emit a DeprecationWarning."""
        import warnings
        db, service_id, song_id = temp_db
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            db.insert_copy_event(
                service_id=service_id,
                song_id=song_id,
                reproduction_type="projection",
            )
        assert any(
            issubclass(w.category, DeprecationWarning)
            and "insert_copy_event" in str(w.message).lower()
            for w in caught
        ), f"Expected DeprecationWarning about insert_copy_event, got: {[str(w.message) for w in caught]}"

    def test_insert_or_get_copy_event_no_warning(self, temp_db):
        """insert_or_get_copy_event() must NOT emit any DeprecationWarning."""
        import warnings
        db, service_id, song_id = temp_db
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            db.insert_or_get_copy_event(
                service_id=service_id,
                song_id=song_id,
                reproduction_type="projection",
            )
        deprecations = [
            w for w in caught if issubclass(w.category, DeprecationWarning)
        ]
        assert len(deprecations) == 0, (
            f"insert_or_get_copy_event() should not emit DeprecationWarning, "
            f"but got: {[str(w.message) for w in deprecations]}"
        )

    def test_duplicate_insert_or_get_returns_same_id(self, temp_db):
        """Calling insert_or_get_copy_event twice with same args returns the same event_id."""
        db, service_id, song_id = temp_db
        id1 = db.insert_or_get_copy_event(
            service_id=service_id,
            song_id=song_id,
            reproduction_type="recording",
        )
        id2 = db.insert_or_get_copy_event(
            service_id=service_id,
            song_id=song_id,
            reproduction_type="recording",
        )
        assert id1 == id2, (
            f"insert_or_get_copy_event must return same id for duplicate insert, "
            f"got {id1} and {id2}"
        )


# ---------------------------------------------------------------------------
# Web query methods moved to Database (#166)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestQuerySongsPaginated:
    """Tests for Database.query_songs_paginated (#166)."""

    @pytest.fixture
    def temp_db(self):
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()
            yield db
            db.close()

    def test_returns_songs_with_performance_count(self, temp_db):
        song_id = temp_db.insert_or_get_song("amazing grace", "Amazing Grace")
        service_id = temp_db.insert_or_update_service(
            "2026-01-01", "AM Worship", "test.pptx", "abc", song_leader="Matt"
        )
        temp_db.insert_service_song(service_id, song_id, ordinal=1)
        rows, total = temp_db.query_songs_paginated()
        assert total == 1
        assert rows[0]["performance_count"] == 1

    def test_search_filters_by_title(self, temp_db):
        temp_db.insert_or_get_song("amazing grace", "Amazing Grace")
        temp_db.insert_or_get_song("holy holy holy", "Holy Holy Holy")
        rows, total = temp_db.query_songs_paginated(search="amazing")
        assert total == 1
        assert rows[0]["display_title"] == "Amazing Grace"

    def test_search_filters_by_credits(self, temp_db):
        song_id = temp_db.insert_or_get_song("amazing grace", "Amazing Grace")
        temp_db.insert_or_get_song_edition(song_id, words_by="John Newton")
        rows, total = temp_db.query_songs_paginated(search="Newton")
        assert total == 1

    def test_pagination(self, temp_db):
        for i in range(5):
            temp_db.insert_or_get_song(f"song {i}", f"Song {i}")
        rows, total = temp_db.query_songs_paginated(page=1, per_page=2)
        assert total == 5
        assert len(rows) == 2
        rows2, _ = temp_db.query_songs_paginated(page=2, per_page=2)
        assert len(rows2) == 2

    def test_sort_by_display_title(self, temp_db):
        temp_db.insert_or_get_song("b song", "B Song")
        temp_db.insert_or_get_song("a song", "A Song")
        rows, _ = temp_db.query_songs_paginated(sort="display_title", sort_dir="asc")
        assert rows[0]["display_title"] == "A Song"

    def test_invalid_sort_column_raises(self, temp_db):
        with pytest.raises(ValueError, match="Invalid sort column"):
            temp_db.query_songs_paginated(sort="DROP TABLE songs")

    def test_empty_database(self, temp_db):
        rows, total = temp_db.query_songs_paginated()
        assert total == 0
        assert rows == []


@pytest.mark.integration
class TestQueryAllServicesPaginated:
    """Tests for Database.query_all_services_paginated (#166)."""

    @pytest.fixture
    def temp_db(self):
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()
            yield db
            db.close()

    def test_returns_services_with_song_count(self, temp_db):
        sid = temp_db.insert_or_update_service(
            "2026-01-01", "AM", "f.pptx", "h1", song_leader="Alice"
        )
        song_id = temp_db.insert_or_get_song("test song", "Test Song")
        temp_db.insert_service_song(sid, song_id, ordinal=1)
        rows, total = temp_db.query_all_services_paginated()
        assert total == 1
        assert rows[0]["song_count"] == 1

    def test_filter_by_leader(self, temp_db):
        temp_db.insert_or_update_service("2026-01-01", "AM", "f.pptx", "h1", song_leader="Alice")
        temp_db.insert_or_update_service("2026-01-08", "PM", "g.pptx", "h2", song_leader="Bob")
        rows, total = temp_db.query_all_services_paginated(q_leader="Alice")
        assert total == 1
        assert rows[0]["song_leader"] == "Alice"

    def test_filter_by_date_range(self, temp_db):
        temp_db.insert_or_update_service("2026-01-01", "AM", "f.pptx", "h1")
        temp_db.insert_or_update_service("2026-06-01", "AM", "g.pptx", "h2")
        rows, total = temp_db.query_all_services_paginated(
            start_date="2026-05-01", end_date="2026-07-01"
        )
        assert total == 1

    def test_invalid_sort_column_raises(self, temp_db):
        with pytest.raises(ValueError, match="Invalid sort column"):
            temp_db.query_all_services_paginated(sort="malicious")

    def test_empty_database(self, temp_db):
        rows, total = temp_db.query_all_services_paginated()
        assert total == 0
        assert rows == []


@pytest.mark.integration
class TestQuerySongById:
    """Tests for Database.query_song_by_id (#166)."""

    @pytest.fixture
    def temp_db(self):
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()
            yield db
            db.close()

    def test_returns_song(self, temp_db):
        song_id = temp_db.insert_or_get_song("amazing grace", "Amazing Grace")
        result = temp_db.query_song_by_id(song_id)
        assert result is not None
        assert result["display_title"] == "Amazing Grace"

    def test_returns_none_for_missing(self, temp_db):
        assert temp_db.query_song_by_id(99999) is None


@pytest.mark.integration
class TestQuerySongEditions:
    """Tests for Database.query_song_editions (#166)."""

    @pytest.fixture
    def temp_db(self):
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()
            yield db
            db.close()

    def test_returns_editions_for_song(self, temp_db):
        song_id = temp_db.insert_or_get_song("amazing grace", "Amazing Grace")
        temp_db.insert_or_get_song_edition(song_id, words_by="John Newton")
        editions = temp_db.query_song_editions(song_id)
        assert len(editions) == 1
        assert editions[0]["words_by"] == "John Newton"

    def test_returns_empty_for_no_editions(self, temp_db):
        song_id = temp_db.insert_or_get_song("new song", "New Song")
        assert temp_db.query_song_editions(song_id) == []


@pytest.mark.integration
class TestQuerySongServices:
    """Tests for Database.query_song_services (#166)."""

    @pytest.fixture
    def temp_db(self):
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()
            yield db
            db.close()

    def test_returns_services_for_song(self, temp_db):
        song_id = temp_db.insert_or_get_song("amazing grace", "Amazing Grace")
        service_id = temp_db.insert_or_update_service(
            "2026-01-01", "AM", "f.pptx", "h1", song_leader="Matt"
        )
        temp_db.insert_service_song(service_id, song_id, ordinal=1)
        services = temp_db.query_song_services(song_id)
        assert len(services) == 1
        assert services[0]["service_date"] == "2026-01-01"
        assert services[0]["song_leader"] == "Matt"

    def test_returns_empty_for_unplayed_song(self, temp_db):
        song_id = temp_db.insert_or_get_song("new song", "New Song")
        assert temp_db.query_song_services(song_id) == []


@pytest.mark.integration
class TestQueryServiceById:
    """Tests for Database.query_service_by_id (#166)."""

    @pytest.fixture
    def temp_db(self):
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()
            yield db
            db.close()

    def test_returns_service(self, temp_db):
        sid = temp_db.insert_or_update_service("2026-01-01", "AM", "f.pptx", "h1")
        result = temp_db.query_service_by_id(sid)
        assert result is not None
        assert result["service_date"] == "2026-01-01"

    def test_returns_none_for_missing(self, temp_db):
        assert temp_db.query_service_by_id(99999) is None


@pytest.mark.integration
class TestQueryServiceSongs:
    """Tests for Database.query_service_songs (#166)."""

    @pytest.fixture
    def temp_db(self):
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()
            yield db
            db.close()

    def test_returns_songs_for_service(self, temp_db):
        song_id = temp_db.insert_or_get_song("amazing grace", "Amazing Grace")
        edition_id = temp_db.insert_or_get_song_edition(song_id, words_by="John Newton")
        service_id = temp_db.insert_or_update_service("2026-01-01", "AM", "f.pptx", "h1")
        temp_db.insert_service_song(service_id, song_id, ordinal=1, song_edition_id=edition_id)
        songs = temp_db.query_service_songs(service_id)
        assert len(songs) == 1
        assert songs[0]["display_title"] == "Amazing Grace"
        assert songs[0]["words_by"] == "John Newton"

    def test_returns_empty_for_empty_service(self, temp_db):
        sid = temp_db.insert_or_update_service("2026-01-01", "AM", "f.pptx", "h1")
        assert temp_db.query_service_songs(sid) == []


class TestCleanupQueries:
    """Tests for cleanup-related database methods (#266)."""

    @pytest.fixture
    def temp_db(self):
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()
            yield db
            db.close()

    def test_query_services_by_date(self, temp_db):
        """query_services_by_date returns services matching the date."""
        temp_db.insert_or_update_service("2026-02-15", "AM Worship", "f.pptx", "h1")
        temp_db.insert_or_update_service("2026-02-16", "PM Worship", "g.pptx", "h2")
        results = temp_db.query_services_by_date("2026-02-15")
        assert len(results) == 1
        assert results[0]["service_name"] == "AM Worship"

    def test_query_services_by_date_with_name_pattern(self, temp_db):
        """query_services_by_date with name_pattern filters by name."""
        temp_db.insert_or_update_service("2026-02-15", "AM Worship", "f.pptx", "h1")
        temp_db.insert_or_update_service("2026-02-15", "PM Worship", "g.pptx", "h2")
        results = temp_db.query_services_by_date("2026-02-15", name_pattern="AM")
        assert len(results) == 1
        assert results[0]["service_name"] == "AM Worship"

    def test_query_services_by_date_no_match(self, temp_db):
        """query_services_by_date returns empty list for no matches."""
        temp_db.insert_or_update_service("2026-02-15", "AM Worship", "f.pptx", "h1")
        assert temp_db.query_services_by_date("1999-01-01") == []

    def test_query_orphaned_songs(self, temp_db):
        """query_orphaned_songs returns songs with no service_songs rows."""
        song_id = temp_db.insert_or_get_song("amazing grace", "Amazing Grace")
        temp_db.insert_or_get_song_edition(song_id, words_by="John Newton")
        results = temp_db.query_orphaned_songs()
        assert len(results) == 1
        assert results[0]["canonical_title"] == "amazing grace"

    def test_query_orphaned_songs_excludes_performed(self, temp_db):
        """query_orphaned_songs excludes songs with service_songs rows."""
        song_id = temp_db.insert_or_get_song("amazing grace", "Amazing Grace")
        service_id = temp_db.insert_or_update_service("2026-02-15", "AM", "f.pptx", "h1")
        temp_db.insert_service_song(service_id, song_id, ordinal=1)
        results = temp_db.query_orphaned_songs()
        assert len(results) == 0

    def test_query_duplicate_services(self, temp_db):
        """query_duplicate_services returns groups with same date+name, different hash."""
        temp_db.insert_or_update_service("2026-02-15", "AM Worship", "f.pptx", "h1")
        temp_db.insert_or_update_service("2026-02-15", "AM Worship", "g.pptx", "h2")
        results = temp_db.query_duplicate_services()
        assert len(results) >= 2
        dates = [r["service_date"] for r in results]
        assert "2026-02-15" in dates

    def test_query_duplicate_services_none(self, temp_db):
        """query_duplicate_services returns empty list when no duplicates."""
        temp_db.insert_or_update_service("2026-02-15", "AM Worship", "f.pptx", "h1")
        results = temp_db.query_duplicate_services()
        assert len(results) == 0

    def test_delete_song(self, temp_db):
        """delete_song removes the song, its editions, and related copy_events."""
        song_id = temp_db.insert_or_get_song("amazing grace", "Amazing Grace")
        edition_id = temp_db.insert_or_get_song_edition(song_id, words_by="John Newton")

        temp_db.delete_song(song_id)

        assert temp_db.query_song_by_id(song_id) is None
        assert temp_db.query_song_editions(song_id) == []

    def test_delete_song_removes_copy_events(self, temp_db):
        """delete_song removes copy_events referencing the song."""
        song_id = temp_db.insert_or_get_song("amazing grace", "Amazing Grace")
        edition_id = temp_db.insert_or_get_song_edition(song_id, words_by="John Newton")
        service_id = temp_db.insert_or_update_service("2026-02-15", "AM", "f.pptx", "h1")
        temp_db.insert_or_get_copy_event(service_id, song_id, "projection", song_edition_id=edition_id)

        temp_db.delete_song(song_id)

        cursor = temp_db.cursor()
        cursor.execute("SELECT COUNT(*) FROM copy_events WHERE song_id = ?", (song_id,))
        assert cursor.fetchone()[0] == 0


@pytest.mark.integration
class TestDatabaseContextManager:
    """Tests for Database __enter__/__exit__ (#290)."""

    def test_context_manager_connects_and_closes(self):
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            with Database(db_path) as db:
                db.init_schema()
                assert db.conn is not None
            assert db.conn is None

    def test_context_manager_closes_on_exception(self):
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            with pytest.raises(RuntimeError):
                with Database(db_path) as db:
                    db.init_schema()
                    raise RuntimeError("boom")
            assert db.conn is None

    def test_context_manager_idempotent_close(self):
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            with Database(db_path) as db:
                db.init_schema()
                db.close()
            # No error on double close via __exit__


@pytest.mark.integration
class TestDatabaseIndexes:
    """Tests for song_id indexes (#308)."""

    @pytest.fixture
    def temp_db(self):
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()
            yield db
            db.close()

    def test_service_songs_has_song_id_index(self, temp_db):
        cursor = temp_db.cursor()
        cursor.execute("PRAGMA index_list('service_songs')")
        indexes = cursor.fetchall()
        has_song_id_index = False
        for idx in indexes:
            cursor.execute(f"PRAGMA index_info('{idx['name']}')")
            columns = [col["name"] for col in cursor.fetchall()]
            if "song_id" in columns:
                has_song_id_index = True
                break
        assert has_song_id_index, "Missing index on service_songs.song_id"

    def test_copy_events_has_song_id_index(self, temp_db):
        cursor = temp_db.cursor()
        cursor.execute("PRAGMA index_list('copy_events')")
        indexes = cursor.fetchall()
        has_song_id_index = False
        for idx in indexes:
            cursor.execute(f"PRAGMA index_info('{idx['name']}')")
            columns = [col["name"] for col in cursor.fetchall()]
            if "song_id" in columns:
                has_song_id_index = True
                break
        assert has_song_id_index, "Missing index on copy_events.song_id"

    def test_services_has_date_index(self, temp_db):
        cursor = temp_db.cursor()
        cursor.execute("PRAGMA index_list('services')")
        indexes = cursor.fetchall()
        has_date_index = False
        for idx in indexes:
            cursor.execute(f"PRAGMA index_info('{idx['name']}')")
            columns = [col["name"] for col in cursor.fetchall()]
            if "service_date" in columns:
                has_date_index = True
                break
        assert has_date_index, "Missing index on services.service_date"

    def test_schema_version_is_2(self, temp_db):
        cursor = temp_db.cursor()
        cursor.execute("PRAGMA user_version")
        assert cursor.fetchone()[0] == 2


@pytest.mark.integration
class TestSortDirValidation:
    """Tests for _safe_sort_dir validation (#316)."""

    @pytest.fixture
    def temp_db(self):
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()
            yield db
            db.close()

    def test_valid_asc(self, temp_db):
        from worship_catalog.db import _safe_sort_dir
        assert _safe_sort_dir("asc") == "ASC"

    def test_valid_desc(self, temp_db):
        from worship_catalog.db import _safe_sort_dir
        assert _safe_sort_dir("DESC") == "DESC"

    def test_invalid_sort_dir_raises(self, temp_db):
        from worship_catalog.db import _safe_sort_dir
        with pytest.raises(ValueError, match="Invalid sort direction"):
            _safe_sort_dir("DROP TABLE songs;")


@pytest.mark.integration
class TestLikeEscaping:
    """Tests for LIKE pattern escaping (#319)."""

    @pytest.fixture
    def temp_db(self):
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()
            yield db
            db.close()

    def test_search_percent_in_query_does_not_match_all(self, temp_db):
        """A search containing '%' should not match everything."""
        temp_db.insert_or_get_song("amazing grace", "Amazing Grace")
        temp_db.insert_or_get_song("how great", "How Great Thou Art")
        rows, total = temp_db.query_songs_paginated(search="%")
        # '%' should not match any real titles (it's escaped)
        assert total == 0

    def test_search_underscore_in_query_literal(self, temp_db):
        """A search containing '_' should match literally, not as wildcard."""
        temp_db.insert_or_get_song("test_song", "Test_Song")
        temp_db.insert_or_get_song("testing", "Testing")
        rows, total = temp_db.query_songs_paginated(search="test_")
        assert total == 1
        assert rows[0]["canonical_title"] == "test_song"
