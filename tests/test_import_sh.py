"""Tests for scripts/failure_tracker.py — safe failure-count management.

These tests verify that the failure tracker handles tricky filenames (single
quotes, shell metacharacters) safely, since it is called from import-new.sh
where filenames are passed as sys.argv arguments rather than interpolated into
code strings.
"""

import json
import subprocess
import sys
from pathlib import Path

FAILURE_TRACKER = Path(__file__).parent.parent / "scripts" / "failure_tracker.py"


def run_tracker(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(FAILURE_TRACKER)] + args,
        capture_output=True,
        text=True,
    )


class TestFailureTrackerSecurity:
    """Filenames with shell metacharacters are handled as literal strings."""

    def test_get_count_for_file_with_single_quote(self, tmp_path: Path) -> None:
        """Filename containing a single quote is read correctly."""
        json_path = tmp_path / ".import_failures.json"
        filename = "don't stop believin.pptx"
        json_path.write_text(
            json.dumps({filename: {"count": 2, "last_failure": "2026-01-01"}})
        )
        result = run_tracker(["get", str(json_path), filename])
        assert result.returncode == 0
        assert result.stdout.strip() == "2"

    def test_get_count_for_file_with_shell_metacharacters(self, tmp_path: Path) -> None:
        """Filename with $(cmd) is treated as a literal string."""
        json_path = tmp_path / ".import_failures.json"
        filename = "song$(whoami).pptx"
        json_path.write_text(
            json.dumps({filename: {"count": 1, "last_failure": "2026-01-01"}})
        )
        result = run_tracker(["get", str(json_path), filename])
        assert result.returncode == 0
        assert result.stdout.strip() == "1"

    def test_get_count_for_file_with_double_quotes(self, tmp_path: Path) -> None:
        """Filename with double quotes is handled safely."""
        json_path = tmp_path / ".import_failures.json"
        filename = 'worship "special" service.pptx'
        json_path.write_text(
            json.dumps({filename: {"count": 3, "last_failure": "2026-01-01"}})
        )
        result = run_tracker(["get", str(json_path), filename])
        assert result.returncode == 0
        assert result.stdout.strip() == "3"

    def test_set_count_for_file_with_single_quote(self, tmp_path: Path) -> None:
        """set command writes correct count for filenames with single quotes."""
        json_path = tmp_path / ".import_failures.json"
        filename = "don't stop.pptx"
        run_tracker(["set", str(json_path), filename, "3"])
        data = json.loads(json_path.read_text())
        assert data[filename]["count"] == 3

    def test_clear_for_file_with_single_quote(self, tmp_path: Path) -> None:
        """clear command removes entry for filenames with single quotes."""
        json_path = tmp_path / ".import_failures.json"
        filename = "don't stop.pptx"
        json_path.write_text(
            json.dumps({filename: {"count": 2, "last_failure": "2026-01-01"}})
        )
        run_tracker(["clear", str(json_path), filename])
        data = json.loads(json_path.read_text())
        assert filename not in data


class TestFailureTrackerBehavior:
    """Core behavior of the failure tracker."""

    def test_get_missing_json_returns_zero(self, tmp_path: Path) -> None:
        json_path = tmp_path / ".import_failures.json"
        result = run_tracker(["get", str(json_path), "some.pptx"])
        assert result.returncode == 0
        assert result.stdout.strip() == "0"

    def test_get_unknown_filename_returns_zero(self, tmp_path: Path) -> None:
        json_path = tmp_path / ".import_failures.json"
        json_path.write_text(json.dumps({}))
        result = run_tracker(["get", str(json_path), "unknown.pptx"])
        assert result.returncode == 0
        assert result.stdout.strip() == "0"

    def test_set_creates_json_file_if_missing(self, tmp_path: Path) -> None:
        json_path = tmp_path / ".import_failures.json"
        run_tracker(["set", str(json_path), "song.pptx", "1"])
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert data["song.pptx"]["count"] == 1

    def test_set_overwrites_existing_count(self, tmp_path: Path) -> None:
        json_path = tmp_path / ".import_failures.json"
        json_path.write_text(
            json.dumps({"song.pptx": {"count": 1, "last_failure": "2026-01-01"}})
        )
        run_tracker(["set", str(json_path), "song.pptx", "2"])
        data = json.loads(json_path.read_text())
        assert data["song.pptx"]["count"] == 2

    def test_set_preserves_other_entries(self, tmp_path: Path) -> None:
        json_path = tmp_path / ".import_failures.json"
        json_path.write_text(
            json.dumps({"other.pptx": {"count": 5, "last_failure": "2026-01-01"}})
        )
        run_tracker(["set", str(json_path), "song.pptx", "1"])
        data = json.loads(json_path.read_text())
        assert data["other.pptx"]["count"] == 5

    def test_clear_unknown_filename_is_noop(self, tmp_path: Path) -> None:
        json_path = tmp_path / ".import_failures.json"
        json_path.write_text(json.dumps({}))
        result = run_tracker(["clear", str(json_path), "unknown.pptx"])
        assert result.returncode == 0

    def test_clear_missing_json_is_noop(self, tmp_path: Path) -> None:
        json_path = tmp_path / ".import_failures.json"
        result = run_tracker(["clear", str(json_path), "song.pptx"])
        assert result.returncode == 0

    def test_set_records_last_failure_timestamp(self, tmp_path: Path) -> None:
        json_path = tmp_path / ".import_failures.json"
        run_tracker(["set", str(json_path), "song.pptx", "1"])
        data = json.loads(json_path.read_text())
        assert "last_failure" in data["song.pptx"]
        assert data["song.pptx"]["last_failure"]  # non-empty
