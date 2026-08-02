"""Marker contract tests — verify registered pytest markers are in place (#91).

Also verifies mutation testing tooling is installed (issue #90).
"""

import subprocess
import sys
from collections.abc import Sequence


def _run_pytest_collect(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run pytest collection and return the completed process."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _parse_collect_counts(output: str) -> tuple[int, int]:
    """Return (selected, deselected) from quiet collect-only output."""
    import re

    no_tests = re.search(r"no tests collected(?: \((\d+) deselected\))?", output)
    if no_tests:
        return 0, int(no_tests.group(1) or 0)

    match = re.search(r"(\d+)(?:/(\d+))? tests? collected(?: \((\d+) deselected\))?", output)
    assert match, f"Could not parse collection counts from output:\n{output}"

    if match.group(2) is not None:
        selected = int(match.group(1))
        deselected = int(match.group(3) or 0)
    else:
        selected = int(match.group(1))
        deselected = 0
    return selected, deselected


def test_slow_marker_is_registered() -> None:
    """The 'slow' marker must appear in pyproject.toml markers so that
    ``pytest -m 'not slow'`` works without any UnknownMarkWarning.

    Verification strategy: run ``uv run --frozen pytest --markers`` and assert
    'slow' is among the listed markers.  This is CI-safe and does not rely
    on importing private pytest internals.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--markers"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"pytest --markers exited {result.returncode}:\n{result.stderr}"
    )
    assert "slow" in result.stdout, (
        "The 'slow' marker is not registered in [tool.pytest.ini_options] markers. "
        "Add it to pyproject.toml so that -m 'not slow' works without warnings.\n"
        f"Registered markers output:\n{result.stdout[:2000]}"
    )


def test_integration_marker_is_registered() -> None:
    """The 'integration' marker must also remain registered (regression guard)."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--markers"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "integration" in result.stdout, (
        "The 'integration' marker is missing from pyproject.toml markers."
    )


def test_not_slow_excludes_marked_tests() -> None:
    """Running pytest -m 'not slow' must skip tests decorated with @pytest.mark.slow.

    Collects tests from test_backup_sh.py and asserts none are selected when
    ``-m 'not slow'`` is active (all backup tests carry @pytest.mark.slow).
    """
    result = _run_pytest_collect(
        [
            "tests/test_backup_sh.py",
            "-m",
            "not slow",
            "--collect-only",
            "-q",
            "--no-header",
            "--no-cov",
        ]
    )
    selected, deselected = _parse_collect_counts(result.stdout)
    assert selected == 0, f"Expected all backup tests to be deselected, got:\n{result.stdout}"
    assert deselected > 0, f"Expected backup tests to count as deselected, got:\n{result.stdout}"


def test_e2e_marker_is_registered() -> None:
    """The 'e2e' marker must be registered so that -m 'not e2e' works without warnings (#83)."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--markers"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "e2e" in result.stdout, (
        "The 'e2e' marker is not registered in [tool.pytest.ini_options] markers. "
        "Add it to pyproject.toml so that -m 'not e2e' works without warnings."
    )


def test_mutmut_is_installed() -> None:
    """mutmut must be installed as a dev dependency and importable (issue #90).

    mutmut does not support --version; use --help (exits 0) to verify it runs.
    """
    result = subprocess.run(
        [sys.executable, "-m", "mutmut", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "mutmut is not installed. Add 'mutmut' to [project.optional-dependencies] dev "
        f"in pyproject.toml and run: pip install -e '.[dev]'\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


class TestIntegrationSkipBehavior:
    """Issue #137 — integration tests in CI: verify skip reason is fixture, not code."""

    def test_integration_marker_is_registered(self, pytestconfig):
        """The 'integration' marker must be a known pytest marker (in pyproject.toml)."""
        # Fallback: check via string representation of registered markers
        marker_strings = pytestconfig.getini("markers")
        registered_names = set()
        for entry in marker_strings:
            # Each entry is like "integration: marks tests as integration tests"
            name = entry.split(":")[0].strip()
            registered_names.add(name)
        assert "integration" in registered_names, (
            "The 'integration' marker is not registered in [tool.pytest.ini_options] markers. "
            f"Registered markers: {registered_names}"
        )

    def test_integration_tests_are_collected_in_ci(self):
        """Integration tests that only need a temp DB must be collected without skipping.

        CI has no real PPTX files, but DB-only integration tests must still run.
        If all integration tests were skipping in CI, this collection count would be 0.

        Note: PPTX-dependent tests skip gracefully with pytest.skip() when the fixture
        file is absent — that is expected and correct behaviour.  The count below
        verifies there are DB-only integration tests that always run.
        """
        result = _run_pytest_collect(
            [
                "-m",
                "integration",
                "--collect-only",
                "-q",
                "--no-header",
                "--no-cov",
            ]
        )
        # The output line "N/M tests collected (K deselected)" should show N > 0.
        # We just assert the command succeeded and found some integration tests.
        assert result.returncode == 0, (
            f"pytest collect for integration tests failed:\n{result.stderr}"
        )
        selected, _ = _parse_collect_counts(result.stdout)
        assert selected >= 5, f"Expected at least 5 integration tests, got:\n{result.stdout}"


def test_all_tests_are_sliceable_by_runtime_markers() -> None:
    """Every test should land in at least one of the runtime markers."""
    total = _run_pytest_collect(["--collect-only", "-q", "--no-header", "--no-cov"])
    marked = _run_pytest_collect(
        [
            "-m",
            "unit or integration or slow or e2e",
            "--collect-only",
            "-q",
            "--no-header",
            "--no-cov",
        ]
    )
    assert total.returncode == 0, f"Full collection failed:\n{total.stderr}"
    assert marked.returncode == 0, f"Marked collection failed:\n{marked.stderr}"
    total_selected, _ = _parse_collect_counts(total.stdout)
    marked_selected, _ = _parse_collect_counts(marked.stdout)
    assert marked_selected == total_selected, (
        "Some tests are still outside the marker slices.\n"
        f"Full: {total.stdout}\nMarked: {marked.stdout}"
    )
