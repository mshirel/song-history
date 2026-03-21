"""Tests for CLI commands."""

import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from click.testing import CliRunner

from worship_catalog.cli import main, validate, import_cmd, ccli, stats, _resolve_library_index
from worship_catalog.db import Database


@pytest.mark.integration
@pytest.mark.slow
class TestValidateCommand:
    """Tests for validate command.

    Marked ``slow`` because the tests that exercise validate invoke the full
    PPTX parsing pipeline (python-pptx + shape extraction), which takes
    ~200–250 ms per test on a developer laptop.
    """

    @pytest.fixture
    def runner(self):
        """Click CLI test runner."""
        return CliRunner()

    @pytest.fixture
    def pptx_file(self):
        """Path to test PPTX file."""
        project_root = Path(__file__).parent.parent
        return project_root / "data" / "AM Worship 2026.02.15.pptx"

    def test_validate_help(self, runner):
        """Show validate command help."""
        result = runner.invoke(main, ["validate", "--help"])
        assert result.exit_code == 0
        assert "Validate" in result.output
        assert "--format" in result.output

    def test_validate_json_format(self, runner, pptx_file):
        """Validate with JSON output format."""
        if not pptx_file.exists():
            pytest.skip(f"Test PPTX not found: {pptx_file}")

        result = runner.invoke(main, ["validate", str(pptx_file), "--format", "json"])
        assert result.exit_code == 0

        # Parse JSON output
        output_json = json.loads(result.output)
        assert "filename" in output_json
        assert "songs" in output_json
        assert isinstance(output_json["songs"], list)

    def test_validate_human_format(self, runner, pptx_file):
        """Validate with human-readable output format."""
        if not pptx_file.exists():
            pytest.skip(f"Test PPTX not found: {pptx_file}")

        result = runner.invoke(main, ["validate", str(pptx_file), "--format", "human"])
        assert result.exit_code == 0
        assert "File:" in result.output
        assert "songs" in result.output.lower()

    def test_validate_file_not_found(self, runner):
        """Validate with non-existent file."""
        result = runner.invoke(main, ["validate", "/nonexistent/file.pptx"])
        assert result.exit_code != 0

    def test_validate_default_format(self, runner, pptx_file):
        """Validate with default format (should be human)."""
        if not pptx_file.exists():
            pytest.skip(f"Test PPTX not found: {pptx_file}")

        result = runner.invoke(main, ["validate", str(pptx_file)])
        assert result.exit_code == 0
        assert "File:" in result.output


@pytest.mark.integration
@pytest.mark.slow
class TestImportCommand:
    """Tests for import command.

    Marked ``slow`` because tests invoke the full import pipeline: PPTX parsing,
    credit resolution, and SQLite writes, which takes ~200–350 ms per test.
    """

    @pytest.fixture
    def runner(self):
        """Click CLI test runner."""
        return CliRunner()

    @pytest.fixture
    def pptx_file(self):
        """Path to test PPTX file."""
        project_root = Path(__file__).parent.parent
        return project_root / "data" / "AM Worship 2026.02.15.pptx"

    def test_import_help(self, runner):
        """Show import command help."""
        result = runner.invoke(main, ["import", "--help"])
        assert result.exit_code == 0
        assert "Import" in result.output
        assert "--db" in result.output

    def test_import_file_to_temp_database(self, runner, pptx_file):
        """Import PPTX file to temporary database."""
        if not pptx_file.exists():
            pytest.skip(f"Test PPTX not found: {pptx_file}")

        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            result = runner.invoke(
                main,
                ["import", str(pptx_file), "--db", str(db_path), "--non-interactive"],
            )
            assert result.exit_code == 0
            assert "Imported" in result.output

            # Verify database was created
            assert db_path.exists()

            # Verify data in database
            db = Database(db_path)
            db.connect()

            cursor = db.conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM songs")
            song_count = cursor.fetchone()[0]
            assert song_count > 0

            db.close()

    def test_import_creates_schema(self, runner, pptx_file):
        """Import creates database schema."""
        if not pptx_file.exists():
            pytest.skip(f"Test PPTX not found: {pptx_file}")

        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            runner.invoke(
                main,
                ["import", str(pptx_file), "--db", str(db_path), "--non-interactive"],
            )

            # Check schema
            db = Database(db_path)
            db.connect()

            cursor = db.conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [row[0] for row in cursor.fetchall()]

            assert "services" in tables
            assert "songs" in tables
            assert "song_editions" in tables
            assert "service_songs" in tables
            assert "copy_events" in tables

            db.close()

    def test_import_file_not_found(self, runner):
        """Import with non-existent file."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            result = runner.invoke(
                main,
                [
                    "import",
                    "/nonexistent/file.pptx",
                    "--db",
                    str(db_path),
                    "--non-interactive",
                ],
            )
            assert result.exit_code != 0

    def test_import_non_pptx_exits_nonzero(self, runner):
        """Importing a non-PPTX file returns exit code 1 (issue #16)."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            bad_file = Path(tmpdir) / "not_a_presentation.pptx"
            bad_file.write_text("this is not a PPTX file")

            result = runner.invoke(
                main,
                ["import", str(bad_file), "--db", str(db_path), "--non-interactive"],
            )
            assert result.exit_code != 0

    def test_import_summary_includes_failure_count(self, runner):
        """Summary line mentions failed count when a file fails (issue #16)."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            bad_file = Path(tmpdir) / "bad.pptx"
            bad_file.write_text("not a pptx")

            result = runner.invoke(
                main,
                ["import", str(bad_file), "--db", str(db_path), "--non-interactive"],
            )
            # Either non-zero exit or explicit failure mention in output
            assert result.exit_code != 0 or "failed" in result.output.lower()

    def test_import_handles_duplicate_songs_in_service(self, runner):
        """Import file with same song appearing multiple times in service.

        When a song is sung more than once in the same service, it should:
        1. Import successfully without constraint violations
        2. Create only one copy_event per reproduction type (not duplicates)
        """
        pptx_file = Path(__file__).parent.parent / "data" / "AM Worship 2026.02.01.pptx"
        if not pptx_file.exists():
            pytest.skip(f"Test PPTX not found: {pptx_file}")

        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Import file with duplicate songs
            result = runner.invoke(
                main,
                ["import", str(pptx_file), "--db", str(db_path), "--non-interactive"],
            )
            assert result.exit_code == 0
            assert "Imported" in result.output

            # Verify database state
            db = Database(db_path)
            db.connect()

            cursor = db.conn.cursor()

            # Check that services were created
            cursor.execute("SELECT COUNT(*) FROM services")
            service_count = cursor.fetchone()[0]
            assert service_count > 0

            # Check copy_events - should have one per song per reproduction type
            cursor.execute(
                """
                SELECT DISTINCT service_id, song_id, song_edition_id, reproduction_type
                FROM copy_events
                """
            )
            copy_events = cursor.fetchall()

            # Each unique (service_id, song_id, song_edition_id, reproduction_type)
            # tuple should appear only once due to UNIQUE constraint
            cursor.execute("SELECT COUNT(*) FROM copy_events")
            total_count = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT DISTINCT service_id, song_id, song_edition_id, reproduction_type
                    FROM copy_events
                )
                """
            )
            unique_count = cursor.fetchone()[0]

            # They should match if no duplicates exist
            assert total_count == unique_count, \
                f"Copy events have duplicates: {total_count} total vs {unique_count} unique"

            db.close()


@pytest.mark.integration
class TestReportCCLICommand:
    """Tests for report ccli command."""

    @pytest.fixture
    def runner(self):
        """Click CLI test runner."""
        return CliRunner()

    @pytest.fixture
    def populated_db(self):
        """Create a temporary database with test data."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()

            # Insert test data
            service_id = db.insert_or_update_service(
                service_date="2026-02-15",
                service_name="Morning Worship",
                source_file="test.pptx",
                source_hash="hash1",
            )

            song_id = db.insert_or_get_song("majesty", "Majesty")

            edition_id = db.insert_or_get_song_edition(
                song_id=song_id,
                publisher="Paperless Hymnal",
                words_by="Jack Hayford",
            )

            db.insert_service_song(
                service_id=service_id,
                song_id=song_id,
                ordinal=1,
                song_edition_id=edition_id,
            )

            db.insert_copy_event(
                service_id=service_id,
                song_id=song_id,
                song_edition_id=edition_id,
                reproduction_type="projection",
                count=1,
                reportable=True,
            )

            db.close()
            yield db_path

    def test_report_ccli_help(self, runner):
        """Show report ccli command help."""
        result = runner.invoke(main, ["report", "ccli", "--help"])
        assert result.exit_code == 0
        assert "ccli" in result.output.lower()
        assert "--from" in result.output
        assert "--to" in result.output

    def test_report_ccli_generates_csv(self, runner, populated_db):
        """Generate CCLI report."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "ccli_report.csv"

            result = runner.invoke(
                main,
                [
                    "report",
                    "ccli",
                    "--from",
                    "2026-02-01",
                    "--to",
                    "2026-02-28",
                    "--db",
                    str(populated_db),
                    "--out",
                    str(output_file),
                ],
            )
            assert result.exit_code == 0
            assert output_file.exists()

            # Verify CSV content
            content = output_file.read_text()
            assert "Date,Service,Title" in content
            assert "2026-02-15" in content
            assert "Majesty" in content

    def test_report_ccli_no_events(self, runner):
        """Report with no events in date range."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()
            db.close()

            output_file = Path(tmpdir) / "ccli_report.csv"

            result = runner.invoke(
                main,
                [
                    "report",
                    "ccli",
                    "--from",
                    "2026-02-01",
                    "--to",
                    "2026-02-28",
                    "--db",
                    str(db_path),
                    "--out",
                    str(output_file),
                ],
            )
            assert result.exit_code == 0


@pytest.mark.integration
class TestReportStatsCommand:
    """Tests for report stats command."""

    @pytest.fixture
    def runner(self):
        """Click CLI test runner."""
        return CliRunner()

    @pytest.fixture
    def populated_db(self):
        """Create a temporary database with test data."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()

            # Insert multiple services with songs
            for i in range(2):
                service_date = f"2026-02-{15 + i:02d}"
                service_id = db.insert_or_update_service(
                    service_date=service_date,
                    service_name="Morning Worship",
                    source_file=f"test{i}.pptx",
                    source_hash=f"hash{i}",
                )

                for j in range(3):
                    canonical = f"song {j}"
                    song_id = db.insert_or_get_song(canonical, f"Song {j}")

                    db.insert_service_song(
                        service_id=service_id,
                        song_id=song_id,
                        ordinal=j + 1,
                    )

                    db.insert_copy_event(
                        service_id=service_id,
                        song_id=song_id,
                        reproduction_type="projection",
                        reportable=True,
                    )

            db.close()
            yield db_path

    def test_report_stats_help(self, runner):
        """Show report stats command help."""
        result = runner.invoke(main, ["report", "stats", "--help"])
        assert result.exit_code == 0
        assert "stats" in result.output.lower()
        assert "--from" in result.output
        assert "--to" in result.output

    def test_report_stats_generates_markdown(self, runner, populated_db):
        """Generate stats report."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "stats_report.md"

            result = runner.invoke(
                main,
                [
                    "report",
                    "stats",
                    "--from",
                    "2026-02-01",
                    "--to",
                    "2026-02-28",
                    "--db",
                    str(populated_db),
                    "--out",
                    str(output_file),
                ],
            )
            assert result.exit_code == 0
            assert output_file.exists()

            # Verify markdown content
            content = output_file.read_text()
            assert "Statistics Report" in content or "Statistics" in content
            assert "Services:" in content or "services" in content.lower()
            assert "Song" in content

    def test_report_stats_no_events(self, runner):
        """Stats report with no events."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()
            db.close()

            output_file = Path(tmpdir) / "stats_report.md"

            result = runner.invoke(
                main,
                [
                    "report",
                    "stats",
                    "--from",
                    "2026-02-01",
                    "--to",
                    "2026-02-28",
                    "--db",
                    str(db_path),
                    "--out",
                    str(output_file),
                ],
            )
            assert result.exit_code == 0


class TestStatsOutputFormat:
    """Contract tests for stats report Markdown output format (#175)."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_stats_markdown_has_required_sections(self, runner, db_with_songs, tmp_path):
        """Stats report must contain Summary, Most Frequent Songs, Services sections."""
        out = tmp_path / "stats.md"
        result = runner.invoke(main, [
            "report", "stats",
            "--db", str(db_with_songs),
            "--from", "0000-01-01", "--to", "9999-12-31",
            "--out", str(out),
        ])
        assert result.exit_code == 0
        content = out.read_text()
        assert "# Song Statistics Report" in content
        assert "## Summary" in content
        assert "## Most Frequent Songs" in content
        assert "## Services" in content

    def test_stats_markdown_song_table_columns(self, runner, db_with_songs, tmp_path):
        """Song frequency table must have Song, Credits, Count columns."""
        out = tmp_path / "stats.md"
        runner.invoke(main, [
            "report", "stats",
            "--db", str(db_with_songs),
            "--from", "0000-01-01", "--to", "9999-12-31",
            "--out", str(out),
        ])
        content = out.read_text()
        assert "| Song |" in content
        assert "Credits" in content
        assert "Count" in content

    def test_stats_markdown_includes_known_song(self, runner, db_with_songs, tmp_path):
        """A song in the DB must appear in the Markdown output."""
        out = tmp_path / "stats.md"
        runner.invoke(main, [
            "report", "stats",
            "--db", str(db_with_songs),
            "--from", "0000-01-01", "--to", "9999-12-31",
            "--out", str(out),
        ])
        content = out.read_text()
        assert "Amazing Grace" in content

    def test_stats_all_songs_flag_overrides_top_20_limit(self, runner, tmp_path):
        """With --all-songs, the report must include every song, not just top 20."""
        db_path = tmp_path / "big.db"
        db = Database(db_path)
        db.connect()
        db.init_schema()
        svc_id = db.insert_or_update_service("2026-01-01", "AM", "f.pptx", "h1")
        for i in range(25):
            song_id = db.insert_or_get_song(f"song {i}", f"Song {i}")
            db.insert_service_song(svc_id, song_id, ordinal=i + 1)
            db.insert_copy_event(svc_id, song_id, "projection", reportable=True)
        db.close()

        out = tmp_path / "stats.md"
        runner.invoke(main, [
            "report", "stats", "--db", str(db_path),
            "--from", "0000-01-01", "--to", "9999-12-31",
            "--out", str(out), "--all-songs",
        ])
        content = out.read_text()
        for i in range(25):
            assert f"Song {i}" in content, f"Song {i} missing with --all-songs"

    def test_stats_services_table_has_date_and_leader(self, runner, db_with_songs, tmp_path):
        """Services section must include date and song leader columns."""
        out = tmp_path / "stats.md"
        runner.invoke(main, [
            "report", "stats",
            "--db", str(db_with_songs),
            "--from", "0000-01-01", "--to", "9999-12-31",
            "--out", str(out),
        ])
        content = out.read_text()
        assert "2026-02-15" in content
        assert "Matt" in content


@pytest.mark.integration
class TestReportStatsLeaderFilter:
    """Tests for report stats --leader option."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    @pytest.fixture
    def leader_db(self):
        """Database with two services led by different leaders."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()

            for i, leader in enumerate(["Alice", "Bob"]):
                service_id = db.insert_or_update_service(
                    service_date=f"2026-02-{15 + i:02d}",
                    service_name="Morning Worship",
                    source_file=f"test{i}.pptx",
                    source_hash=f"hash{i}",
                    song_leader=leader,
                )
                song_id = db.insert_or_get_song(f"song {i}", f"Song {i}")
                db.insert_service_song(service_id=service_id, song_id=song_id, ordinal=1)
                db.insert_copy_event(
                    service_id=service_id,
                    song_id=song_id,
                    reproduction_type="projection",
                    reportable=True,
                )

            db.close()
            yield db_path

    def test_stats_leader_filter_restricts_output(self, runner, leader_db):
        """--leader filters the stats report to that leader's services."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "stats.md"

            result = runner.invoke(
                main,
                [
                    "report", "stats",
                    "--db", str(leader_db),
                    "--leader", "Alice",
                    "--out", str(output_file),
                ],
            )
            assert result.exit_code == 0
            content = output_file.read_text()
            assert "Alice" in content
            assert "Bob" not in content

    def test_stats_leader_header_in_report(self, runner, leader_db):
        """--leader writes a Song Leader line in the report."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "stats.md"

            runner.invoke(
                main,
                [
                    "report", "stats",
                    "--db", str(leader_db),
                    "--leader", "Alice",
                    "--out", str(output_file),
                ],
            )
            content = output_file.read_text()
            assert "**Song Leader:**" in content

    def test_stats_leader_filter_help(self, runner):
        """--leader option appears in help."""
        result = runner.invoke(main, ["report", "stats", "--help"])
        assert "--leader" in result.output

    def test_stats_leader_breakdown_included_without_filter(self, runner, leader_db):
        """Without --leader, report includes a 'By Song Leader' section."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "stats.md"
            result = runner.invoke(
                main,
                ["report", "stats", "--db", str(leader_db), "--out", str(output_file)],
            )
            assert result.exit_code == 0
            content = output_file.read_text()
            assert "By Song Leader" in content

    def test_stats_leader_breakdown_shows_each_leader(self, runner, leader_db):
        """Breakdown section contains a heading for each leader."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "stats.md"
            runner.invoke(
                main,
                ["report", "stats", "--db", str(leader_db), "--out", str(output_file)],
            )
            content = output_file.read_text()
            assert "### Alice" in content
            assert "### Bob" in content

    def test_stats_leader_breakdown_shows_songs(self, runner, leader_db):
        """Breakdown lists each leader's songs."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "stats.md"
            runner.invoke(
                main,
                ["report", "stats", "--db", str(leader_db), "--out", str(output_file)],
            )
            content = output_file.read_text()
            assert "Song 0" in content  # Alice's song
            assert "Song 1" in content  # Bob's song

    def test_stats_leader_breakdown_omitted_when_filtered(self, runner, leader_db):
        """With --leader, the breakdown section is NOT included."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "stats.md"
            runner.invoke(
                main,
                [
                    "report", "stats",
                    "--db", str(leader_db),
                    "--leader", "Alice",
                    "--out", str(output_file),
                ],
            )
            content = output_file.read_text()
            assert "By Song Leader" not in content

    def test_stats_leader_breakdown_service_count(self, runner, leader_db):
        """Breakdown shows service count in each leader heading."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "stats.md"
            runner.invoke(
                main,
                ["report", "stats", "--db", str(leader_db), "--out", str(output_file)],
            )
            content = output_file.read_text()
            # Each leader has 1 service in the fixture
            assert "1 service" in content


@pytest.mark.integration
class TestRepairCreditsCommand:
    """Tests for repair-credits command."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    @pytest.fixture
    def db_with_missing_credits(self):
        """Database with a song that has no credits."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()

            service_id = db.insert_or_update_service(
                service_date="2026-02-15",
                service_name="Morning Worship",
                source_file="test.pptx",
                source_hash="hash1",
            )
            song_id = db.insert_or_get_song("amazing grace", "Amazing Grace")
            db.insert_service_song(service_id=service_id, song_id=song_id, ordinal=1)

            db.close()
            yield db_path

    def test_repair_credits_help(self, runner):
        result = runner.invoke(main, ["repair-credits", "--help"])
        assert result.exit_code == 0
        assert "--library-index" in result.output
        assert "--dry-run" in result.output
        assert "--ocr" in result.output

    def test_repair_credits_no_missing(self, runner):
        """repair-credits with no missing credits exits cleanly."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()
            db.close()

            result = runner.invoke(main, ["repair-credits", "--db", str(db_path)])
            assert result.exit_code == 0
            assert "No songs" in result.output

    def test_repair_credits_dry_run_with_library(self, runner, db_with_missing_credits):
        """repair-credits --dry-run uses library index without writing to DB."""
        with TemporaryDirectory() as tmpdir:
            # Create a minimal library index that has Amazing Grace
            index_path = Path(tmpdir) / "index.json"
            index = {
                "amazing grace": {
                    "display_title": "Amazing Grace",
                    "words_by": "John Newton",
                    "music_by": None,
                    "arranger": None,
                }
            }
            index_path.write_text(__import__("json").dumps(index))

            result = runner.invoke(
                main,
                [
                    "repair-credits",
                    "--db", str(db_with_missing_credits),
                    "--library-index", str(index_path),
                    "--dry-run",
                ],
            )
            assert result.exit_code == 0
            assert "Dry run" in result.output
            assert "1" in result.output  # would update 1 song

    def test_repair_credits_applies_library_credits(self, runner, db_with_missing_credits):
        """repair-credits writes credits from library index to DB."""
        with TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "index.json"
            index = {
                "amazing grace": {
                    "display_title": "Amazing Grace",
                    "words_by": "John Newton",
                    "music_by": None,
                    "arranger": None,
                }
            }
            index_path.write_text(__import__("json").dumps(index))

            result = runner.invoke(
                main,
                [
                    "repair-credits",
                    "--db", str(db_with_missing_credits),
                    "--library-index", str(index_path),
                ],
            )
            assert result.exit_code == 0

            # Verify credits are now in DB
            db = Database(db_with_missing_credits)
            db.connect()
            cursor = db.conn.cursor()
            cursor.execute(
                """
                SELECT se.words_by FROM songs s
                JOIN song_editions se ON se.song_id = s.id
                WHERE s.canonical_title = 'amazing grace'
                """
            )
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == "John Newton"
            db.close()

    def test_repair_credits_not_in_library(self, runner, db_with_missing_credits):
        """repair-credits reports when a song is not found in library."""
        with TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "index.json"
            index_path.write_text("{}")  # empty index

            result = runner.invoke(
                main,
                [
                    "repair-credits",
                    "--db", str(db_with_missing_credits),
                    "--library-index", str(index_path),
                ],
            )
            assert result.exit_code == 0
            # No credits found, should skip
            assert "skipping" in result.output.lower() or "No credits" in result.output


@pytest.mark.integration
class TestLibraryIndexCommand:
    """Tests for library index command."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_library_index_help(self, runner):
        result = runner.invoke(main, ["library", "index", "--help"])
        assert result.exit_code == 0
        assert "--path" in result.output
        assert "--out" in result.output

    def test_library_index_requires_path(self, runner):
        """--path is required."""
        result = runner.invoke(main, ["library", "index"])
        assert result.exit_code != 0

    def test_library_index_nonexistent_path(self, runner):
        """--path that doesn't exist is rejected by Click."""
        result = runner.invoke(main, ["library", "index", "--path", "/nonexistent/library"])
        assert result.exit_code != 0

    def test_library_index_empty_directory(self, runner):
        """library index on empty directory writes empty JSON."""
        with TemporaryDirectory() as tmpdir:
            lib_dir = Path(tmpdir) / "library"
            lib_dir.mkdir()
            out_path = Path(tmpdir) / "index.json"

            result = runner.invoke(
                main,
                ["library", "index", "--path", str(lib_dir), "--out", str(out_path)],
            )
            assert result.exit_code == 0
            assert out_path.exists()

            import json
            data = json.loads(out_path.read_text())
            assert isinstance(data, dict)


@pytest.mark.integration
@pytest.mark.slow
class TestCLIIntegration:
    """End-to-end CLI integration tests.

    Marked ``slow`` because test_full_workflow runs the entire
    validate → import → report pipeline end-to-end (~430 ms).
    """

    @pytest.fixture
    def runner(self):
        """Click CLI test runner."""
        return CliRunner()

    @pytest.fixture
    def pptx_file(self):
        """Path to test PPTX file."""
        project_root = Path(__file__).parent.parent
        return project_root / "data" / "AM Worship 2026.02.15.pptx"

    def test_full_workflow(self, runner, pptx_file):
        """Test full workflow: validate -> import -> report."""
        if not pptx_file.exists():
            pytest.skip(f"Test PPTX not found: {pptx_file}")

        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            ccli_report = Path(tmpdir) / "ccli.csv"
            stats_report = Path(tmpdir) / "stats.md"

            # 1. Validate
            result = runner.invoke(
                main, ["validate", str(pptx_file), "--format", "json"]
            )
            assert result.exit_code == 0

            # 2. Import
            result = runner.invoke(
                main,
                ["import", str(pptx_file), "--db", str(db_path), "--non-interactive"],
            )
            assert result.exit_code == 0

            # 3. Generate CCLI report
            result = runner.invoke(
                main,
                [
                    "report",
                    "ccli",
                    "--from",
                    "2026-02-01",
                    "--to",
                    "2026-02-28",
                    "--db",
                    str(db_path),
                    "--out",
                    str(ccli_report),
                ],
            )
            assert result.exit_code == 0
            assert ccli_report.exists()

            # 4. Generate stats report
            result = runner.invoke(
                main,
                [
                    "report",
                    "stats",
                    "--from",
                    "2026-02-01",
                    "--to",
                    "2026-02-28",
                    "--db",
                    str(db_path),
                    "--out",
                    str(stats_report),
                ],
            )
            assert result.exit_code == 0
            assert stats_report.exists()

    def test_main_help(self, runner):
        """Show main help."""
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Worship" in result.output or "worship" in result.output.lower()

    def test_main_version(self, runner):
        """Show version."""
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1" in result.output


class TestOcrCapOptions:
    """Tests for --max-ocr-calls and --unlimited-ocr CLI options."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_import_help_shows_max_ocr_calls(self, runner):
        result = runner.invoke(main, ["import", "--help"])
        assert result.exit_code == 0
        assert "--max-ocr-calls" in result.output

    def test_import_help_shows_unlimited_ocr(self, runner):
        result = runner.invoke(main, ["import", "--help"])
        assert result.exit_code == 0
        assert "--unlimited-ocr" in result.output

    def test_repair_credits_help_shows_max_ocr_calls(self, runner):
        result = runner.invoke(main, ["repair-credits", "--help"])
        assert result.exit_code == 0
        assert "--max-ocr-calls" in result.output

    def test_repair_credits_help_shows_unlimited_ocr(self, runner):
        result = runner.invoke(main, ["repair-credits", "--help"])
        assert result.exit_code == 0
        assert "--unlimited-ocr" in result.output

    def test_repair_credits_ocr_zero_cap_skips_ocr(self, runner):
        """--max-ocr-calls 0 with --ocr should not attempt any OCR calls."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)
            db.connect()
            db.init_schema()

            service_id = db.insert_or_update_service(
                service_date="2026-02-15",
                service_name="Morning Worship",
                source_file="test.pptx",
                source_hash="hash1",
            )
            song_id = db.insert_or_get_song("amazing grace", "Amazing Grace")
            db.insert_service_song(service_id=service_id, song_id=song_id, ordinal=1)
            db.close()

            import os
            result = runner.invoke(
                main,
                [
                    "repair-credits",
                    "--db", str(db_path),
                    "--ocr",
                    "--max-ocr-calls", "0",
                ],
                env={**os.environ, "ANTHROPIC_API_KEY": "sk-ant-test"},
            )
            assert result.exit_code == 0
            # Should mention the cap was reached or 0 OCR calls
            output_lower = result.output.lower()
            assert (
                "0" in result.output
                or "cap" in output_lower
                or "limit" in output_lower
            )

    def test_repair_credits_ocr_preflight_shows_count(self, runner):
        """repair-credits --ocr prints a pre-flight count of songs needing OCR."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            index_path = Path(tmpdir) / "index.json"
            index_path.write_text("{}")  # empty — all songs will need OCR

            db = Database(db_path)
            db.connect()
            db.init_schema()

            service_id = db.insert_or_update_service(
                service_date="2026-02-15",
                service_name="Morning Worship",
                source_file="test.pptx",
                source_hash="hash1",
            )
            song_id = db.insert_or_get_song("amazing grace", "Amazing Grace")
            db.insert_service_song(service_id=service_id, song_id=song_id, ordinal=1)
            db.close()

            import os
            result = runner.invoke(
                main,
                [
                    "repair-credits",
                    "--db", str(db_path),
                    "--library-index", str(index_path),
                    "--ocr",
                    "--max-ocr-calls", "0",
                ],
                env={**os.environ, "ANTHROPIC_API_KEY": "sk-ant-test"},
            )
            assert result.exit_code == 0
            # Pre-flight message should include the count of songs needing OCR
            assert "1" in result.output  # 1 song needs OCR


class TestResolveLibraryIndex:
    """Tests for the _resolve_library_index helper."""

    def test_returns_local_path_when_exists(self, tmp_path):
        """Returns the local path when it exists, regardless of bundled data."""
        index = tmp_path / "my_index.json"
        index.write_text("{}")
        result = _resolve_library_index(str(index))
        assert result == index

    def test_falls_back_to_bundled_when_local_missing(self, tmp_path):
        """Falls back to the bundled package data when the local path is absent."""
        nonexistent = str(tmp_path / "no_such_file.json")
        result = _resolve_library_index(nonexistent)
        # The bundled index ships with the package and should always exist
        assert result.exists(), "Bundled library_index.json not found in package data"
        assert result.name == "library_index.json"

    def test_bundled_index_is_valid_json(self, tmp_path):
        """Bundled library index can be parsed as JSON."""
        nonexistent = str(tmp_path / "no_such_file.json")
        result = _resolve_library_index(nonexistent)
        data = json.loads(result.read_text())
        assert isinstance(data, dict)
        assert len(data) > 0

    def test_returns_nonexistent_path_unchanged_if_no_bundle(self, tmp_path, monkeypatch):
        """Returns the original path when both local and bundle are missing (import guards work)."""
        # This tests the fallback path — patch importlib.resources to return a missing path
        import importlib.resources
        nonexistent = tmp_path / "missing.json"

        class _FakeTraversable:
            def __truediv__(self, other):
                return self
            def __str__(self):
                return str(tmp_path / "fake_bundle.json")  # also doesn't exist

        monkeypatch.setattr(importlib.resources, "files", lambda *a, **kw: _FakeTraversable())
        result = _resolve_library_index(str(nonexistent))
        # Should return the original path (doesn't crash)
        assert isinstance(result, Path)


class TestBareExceptLogging:
    """Bare except blocks must log errors, not swallow them silently (#99)."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_validate_logs_exception_on_corrupt_pptx(self, tmp_path, caplog):
        """validate command must log exceptions, not swallow them silently."""
        import logging

        runner = CliRunner()
        corrupt_pptx = tmp_path / "bad.pptx"
        corrupt_pptx.write_bytes(b"not a real pptx")

        with caplog.at_level(logging.ERROR, logger="worship_catalog"):
            result = runner.invoke(main, ["validate", str(corrupt_pptx)])

        # Must fail non-zero AND log the error
        assert result.exit_code != 0 or "error" in result.output.lower()
        # After fix: logger must have emitted an error record
        logged_errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert logged_errors, (
            "validate must log exceptions via logger.exception() or logger.error(), "
            "not just print to stderr without a log record"
        )

    def test_import_outer_exception_is_logged(self, tmp_path, caplog):
        """The outer except in import_cmd must log the exception (#99).

        When the database directory does not exist, import_cmd raises before
        even processing files. This outer handler must log, not just print.
        """
        import logging

        runner = CliRunner()
        # Use a valid-looking pptx path that exists so Click accepts it
        pptx = tmp_path / "test.pptx"
        pptx.write_bytes(b"PK")  # minimal bytes — will fail on extraction
        nonexistent_db = str(tmp_path / "no_dir" / "worship.db")

        with caplog.at_level(logging.ERROR, logger="worship_catalog"):
            result = runner.invoke(main, ["import", str(pptx), "--db", nonexistent_db])

        assert result.exit_code != 0
        logged_errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert logged_errors, (
            "import outer except must call logger.exception() or logger.error()"
        )

    def test_ccli_report_logs_exception_on_bad_db(self, tmp_path, caplog):
        """ccli report command must log exceptions (#99)."""
        import logging

        runner = CliRunner()
        bad_db = str(tmp_path / "no_dir" / "worship.db")

        with caplog.at_level(logging.ERROR, logger="worship_catalog"):
            result = runner.invoke(main, ["report", "ccli", "--db", bad_db])

        assert result.exit_code != 0
        logged_errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert logged_errors, (
            "ccli report outer except must call logger.exception() or logger.error()"
        )

    def test_stats_report_logs_exception_on_bad_db(self, tmp_path, caplog):
        """stats report command must log exceptions (#99)."""
        import logging

        runner = CliRunner()
        bad_db = str(tmp_path / "no_dir" / "worship.db")

        with caplog.at_level(logging.ERROR, logger="worship_catalog"):
            result = runner.invoke(main, ["report", "stats", "--db", bad_db])

        assert result.exit_code != 0
        logged_errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert logged_errors, (
            "stats report outer except must call logger.exception() or logger.error()"
        )

    def test_library_index_logs_exception_on_error(self, tmp_path, caplog):
        """library index command must log exceptions (#99)."""
        import logging

        runner = CliRunner()
        # Pass a real dir so Click accepts --path, but scrape_library will error
        # because there are no .ppt files (exit is 0 in that case) — we need a
        # path that causes an actual exception.  Patch save_library_index to raise.
        import unittest.mock

        with unittest.mock.patch(
            "worship_catalog.library.scrape_library",
            side_effect=RuntimeError("simulated scrape failure"),
        ):
            with caplog.at_level(logging.ERROR, logger="worship_catalog"):
                result = runner.invoke(
                    main, ["library", "index", "--path", str(tmp_path)]
                )

        assert result.exit_code != 0
        logged_errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert logged_errors, (
            "library index outer except must call logger.exception() or logger.error()"
        )


class TestCliNamedConstants:
    """Named constants replace magic numbers in cli.py (#22)."""

    def test_report_date_min_constant_exists(self):
        """_REPORT_DATE_MIN is defined as the open-ended start sentinel."""
        from worship_catalog.cli import _REPORT_DATE_MIN

        assert _REPORT_DATE_MIN == "0000-01-01"

    def test_report_date_max_constant_exists(self):
        """_REPORT_DATE_MAX is defined as the open-ended end sentinel."""
        from worship_catalog.cli import _REPORT_DATE_MAX

        assert _REPORT_DATE_MAX == "9999-12-31"

    def test_stats_top_songs_constant_exists_and_is_20(self):
        """_STATS_TOP_SONGS is defined as a positive integer."""
        from worship_catalog.cli import _STATS_TOP_SONGS

        assert isinstance(_STATS_TOP_SONGS, int)
        assert _STATS_TOP_SONGS == 20


# ---------------------------------------------------------------------------
# Issue #134 — CCLI CSV commas corrupt output
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCcliCsvCommaInTitle:
    """CCLI report must use csv module so titles with commas are properly quoted — issue #134."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    @pytest.fixture
    def db_with_comma_title(self, tmp_path):
        """Database containing a song whose title contains a comma."""
        db_path = tmp_path / "comma_test.db"
        db = Database(db_path)
        db.connect()
        db.init_schema()

        service_id = db.insert_or_update_service(
            service_date="2026-03-01",
            service_name="Morning Worship",
            source_file="test.pptx",
            source_hash="comma-hash",
        )
        song_id = db.insert_or_get_song("amazing, grace", "Amazing, Grace")
        edition_id = db.insert_or_get_song_edition(
            song_id=song_id,
            publisher="Paperless Hymnal",
            words_by="John Newton",
        )
        db.insert_service_song(
            service_id=service_id,
            song_id=song_id,
            ordinal=1,
            song_edition_id=edition_id,
        )
        db.insert_or_get_copy_event(
            service_id=service_id,
            song_id=song_id,
            song_edition_id=edition_id,
            reproduction_type="projection",
            count=1,
            reportable=True,
        )
        db.close()
        return db_path

    def test_ccli_csv_quotes_title_with_comma(self, runner, db_with_comma_title, tmp_path):
        """A song title containing a comma must be double-quoted in the CSV output."""
        import csv
        out = tmp_path / "report.csv"
        result = runner.invoke(
            main,
            ["report", "ccli", "--db", str(db_with_comma_title), "--out", str(out)],
        )
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert out.exists()

        content = out.read_text()
        # The title with comma must appear properly quoted (csv module style)
        assert '"Amazing, Grace"' in content, (
            f"Expected quoted title in CSV, got:\n{content}"
        )

    def test_ccli_csv_is_parseable_by_csv_reader(self, runner, db_with_comma_title, tmp_path):
        """The output CSV must be parseable by csv.reader with the correct number of columns."""
        import csv
        out = tmp_path / "report.csv"
        result = runner.invoke(
            main,
            ["report", "ccli", "--db", str(db_with_comma_title), "--out", str(out)],
        )
        assert result.exit_code == 0
        content = out.read_text()

        # Filter out comment lines (lines starting with #) and blank lines
        data_lines = [
            line for line in content.splitlines()
            if line.strip() and not line.startswith("#")
        ]
        reader = csv.reader(data_lines)
        rows = list(reader)
        assert rows, "CSV must have at least a header row"
        # Header row
        assert len(rows[0]) == 6, f"Header must have 6 columns, got {len(rows[0])}: {rows[0]}"
        # Data rows must also have 6 columns
        for row in rows[1:]:
            assert len(row) == 6, (
                f"Data row must have 6 columns, got {len(row)}: {row}"
            )

    def test_ccli_csv_correct_title_value_after_parse(self, runner, db_with_comma_title, tmp_path):
        """After parsing with csv.reader, the title field must equal the original title."""
        import csv
        out = tmp_path / "report.csv"
        runner.invoke(
            main,
            ["report", "ccli", "--db", str(db_with_comma_title), "--out", str(out)],
        )
        content = out.read_text()
        data_lines = [
            line for line in content.splitlines()
            if line.strip() and not line.startswith("#")
        ]
        reader = csv.reader(data_lines)
        rows = list(reader)
        # Skip header — find the data row
        data_rows = rows[1:]
        assert any(row[2] == "Amazing, Grace" for row in data_rows), (
            f"Expected title 'Amazing, Grace' in column 2, rows: {data_rows}"
        )

    def test_ccli_csv_happy_path_no_commas(self, runner, tmp_path):
        """Existing happy path: title without commas still works correctly."""
        import csv
        db_path = tmp_path / "simple.db"
        db = Database(db_path)
        db.connect()
        db.init_schema()
        service_id = db.insert_or_update_service(
            service_date="2026-03-02",
            service_name="Evening Worship",
            source_file="s.pptx",
            source_hash="simple",
        )
        song_id = db.insert_or_get_song("majesty", "Majesty")
        edition_id = db.insert_or_get_song_edition(song_id=song_id, publisher="PH")
        db.insert_service_song(service_id, song_id, ordinal=1, song_edition_id=edition_id)
        db.insert_or_get_copy_event(service_id, song_id, "projection", song_edition_id=edition_id, reportable=True)
        db.close()

        out = tmp_path / "out.csv"
        result = runner.invoke(
            main,
            ["report", "ccli", "--db", str(db_path), "--out", str(out)],
        )
        assert result.exit_code == 0
        content = out.read_text()
        data_lines = [l for l in content.splitlines() if l.strip() and not l.startswith("#")]
        rows = list(csv.reader(data_lines))
        assert any("Majesty" in row for row in rows[1:]), f"Majesty not found in {rows}"


# ---------------------------------------------------------------------------
# Issue #192 — CCLI CSV must not inject non-CSV comment lines
# ---------------------------------------------------------------------------


class TestCcliCsvValidity:
    """CCLI CSV output must be valid CSV with no comment lines."""

    def _setup_db_with_events(self, db_path: Path) -> None:
        """Insert sample services and copy events for CCLI report."""
        db = Database(db_path)
        db.connect()
        db.init_schema()
        song_id = db.insert_or_get_song("amazing_grace", "Amazing Grace")
        svc1 = db.insert_or_update_service(
            "2025-01-05", "Sunday AM", str(db_path), "hash1"
        )
        svc2 = db.insert_or_update_service(
            "2025-01-12", "Sunday AM", str(db_path), "hash2"
        )
        for svc_id in (svc1, svc2):
            db.insert_or_get_copy_event(
                svc_id, song_id, "projection", reportable=True
            )
        db.close()

    def test_ccli_csv_has_no_comment_lines(self, tmp_path: Path) -> None:
        """Every line in the CSV output must be parseable by csv.reader."""
        db_path = tmp_path / "test.db"
        out_path = tmp_path / "ccli.csv"
        self._setup_db_with_events(db_path)

        runner = CliRunner()
        result = runner.invoke(main, [
            "report", "ccli",
            "--db", str(db_path),
            "--out", str(out_path),
        ])
        assert result.exit_code == 0

        content = out_path.read_text()
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if not stripped:
                continue  # blank lines are acceptable between groups
            assert not stripped.startswith("#"), (
                f"Line {i} is a comment, not valid CSV: {stripped!r}"
            )

    def test_ccli_csv_parseable_by_csv_reader(self, tmp_path: Path) -> None:
        """The entire CSV file must be parseable by Python's csv.reader."""
        import csv

        db_path = tmp_path / "test.db"
        out_path = tmp_path / "ccli.csv"
        self._setup_db_with_events(db_path)

        runner = CliRunner()
        runner.invoke(main, [
            "report", "ccli",
            "--db", str(db_path),
            "--out", str(out_path),
        ])

        with open(out_path) as f:
            reader = csv.reader(f)
            rows = list(reader)

        # All rows should have the same number of columns as the header
        header = rows[0]
        for i, row in enumerate(rows[1:], 2):
            if not row:
                continue  # blank rows are acceptable
            assert len(row) == len(header), (
                f"Row {i} has {len(row)} columns, expected {len(header)}: {row}"
            )


class TestReportHelpDiscoverability:
    """Verify report subcommands are discoverable via --help (#178)."""

    def test_ccli_command_visible_in_report_help(self) -> None:
        """The ccli subcommand must appear in 'report --help' output."""
        runner = CliRunner()
        result = runner.invoke(main, ["report", "--help"])
        assert result.exit_code == 0
        assert "ccli" in result.output, (
            f"'ccli' not found in report --help output:\n{result.output}"
        )
