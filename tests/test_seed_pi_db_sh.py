"""Tests for scripts/seed-pi-db.sh — closes #153."""

import sqlite3
import subprocess
from pathlib import Path

import pytest

SEED_SCRIPT = Path(__file__).parent.parent / "scripts" / "seed-pi-db.sh"


def _make_valid_db(path: Path) -> None:
    """Create a minimal but valid SQLite DB with a services table."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE services (id INTEGER PRIMARY KEY, service_date TEXT, service_name TEXT)"
    )
    conn.execute("INSERT INTO services (service_date, service_name) VALUES ('2026-01-01', 'Sunday AM')")
    conn.execute("INSERT INTO services (service_date, service_name) VALUES ('2026-03-15', 'Sunday PM')")
    conn.commit()
    conn.close()


def _make_corrupt_db(path: Path) -> None:
    """Write a file that is not a valid SQLite database."""
    path.write_bytes(b"this is not a sqlite database" * 100)


@pytest.mark.slow
class TestSeedPiDb:
    """seed-pi-db.sh must validate source DB before attempting to copy — closes #153."""

    def test_script_exists_and_is_executable(self) -> None:
        """seed-pi-db.sh must exist in scripts/."""
        assert SEED_SCRIPT.exists(), f"seed-pi-db.sh not found at {SEED_SCRIPT}"

    def test_exits_1_with_no_args(self) -> None:
        """seed-pi-db.sh exits non-zero when called with no arguments."""
        result = subprocess.run(
            ["bash", str(SEED_SCRIPT)],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, "Must exit non-zero when no PI_HOST argument given"

    def test_exits_1_on_corrupt_db(self, tmp_path: Path) -> None:
        """seed-pi-db.sh must exit 1 when the source DB fails integrity check."""
        corrupt_db = tmp_path / "corrupt.db"
        _make_corrupt_db(corrupt_db)

        result = subprocess.run(
            ["bash", str(SEED_SCRIPT), "pi@fake-pi-host", str(corrupt_db)],
            capture_output=True,
            text=True,
            input="\n",  # answer any prompts with empty/no
        )
        assert result.returncode != 0, (
            "seed-pi-db.sh must exit non-zero for a corrupt source DB"
        )
        combined = result.stdout + result.stderr
        assert any(kw in combined.lower() for kw in ("fail", "error", "integrity")), (
            f"Expected error message about integrity check, got: {combined!r}"
        )

    def test_prints_service_count_for_valid_db(self, tmp_path: Path) -> None:
        """seed-pi-db.sh must print the service count from a valid DB."""
        valid_db = tmp_path / "worship.db"
        _make_valid_db(valid_db)

        # Pass 'n' to abort before the scp step — we only want pre-copy output
        result = subprocess.run(
            ["bash", str(SEED_SCRIPT), "pi@fake-pi-host", str(valid_db)],
            capture_output=True,
            text=True,
            input="n\n",  # decline the copy confirmation
        )
        combined = result.stdout + result.stderr
        # Should print the service count (2 services)
        assert "2" in combined, (
            f"Expected service count (2) in output, got: {combined!r}"
        )

    def test_prints_date_range_for_valid_db(self, tmp_path: Path) -> None:
        """seed-pi-db.sh must print the date range from the services table."""
        valid_db = tmp_path / "worship.db"
        _make_valid_db(valid_db)

        result = subprocess.run(
            ["bash", str(SEED_SCRIPT), "pi@fake-pi-host", str(valid_db)],
            capture_output=True,
            text=True,
            input="n\n",
        )
        combined = result.stdout + result.stderr
        # Should show min/max dates from services
        assert "2026-01-01" in combined or "2026-03-15" in combined, (
            f"Expected date range in output, got: {combined!r}"
        )

    def test_aborts_cleanly_when_user_declines(self, tmp_path: Path) -> None:
        """When user answers N to the copy prompt, script exits 0 without copying."""
        valid_db = tmp_path / "worship.db"
        _make_valid_db(valid_db)

        result = subprocess.run(
            ["bash", str(SEED_SCRIPT), "pi@fake-pi-host", str(valid_db)],
            capture_output=True,
            text=True,
            input="n\n",
        )
        # Exit 0 (clean abort), no scp attempted (which would fail anyway)
        assert result.returncode == 0, (
            f"Declining the copy should exit 0 (clean abort), got: {result.returncode}"
        )
        combined = result.stdout + result.stderr
        assert "abort" in combined.lower() or "aborted" in combined.lower(), (
            f"Expected 'Aborted' message, got: {combined!r}"
        )
