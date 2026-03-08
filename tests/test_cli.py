"""Tests for CLI commands."""

import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from click.testing import CliRunner

from worship_catalog.cli import main, validate, import_cmd, ccli, stats
from worship_catalog.db import Database


@pytest.mark.integration
class TestValidateCommand:
    """Tests for validate command."""

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
class TestImportCommand:
    """Tests for import command."""

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


@pytest.mark.integration
class TestCLIIntegration:
    """End-to-end CLI integration tests."""

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
