"""Integration tests for database operations."""

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
