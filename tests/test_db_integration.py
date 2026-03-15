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
