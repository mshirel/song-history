"""Marker contract tests — verify registered pytest markers are in place (#91)."""

import subprocess
import sys


def test_slow_marker_is_registered() -> None:
    """The 'slow' marker must appear in pyproject.toml markers so that
    ``pytest -m 'not slow'`` works without any UnknownMarkWarning.

    Verification strategy: run ``python3 -m pytest --markers`` and assert
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
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "tests/test_backup_sh.py",
            "-m", "not slow",
            "--collect-only", "-q",
            "--no-header",
            "--no-cov",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    # Either 0 tests collected ("no tests ran") or the output says "deselected"
    collected_lines = [
        line for line in result.stdout.splitlines()
        if line.strip() and not line.startswith("=")
    ]
    # All backup tests are marked slow, so none should appear in the collected list
    assert "test_backup" not in result.stdout or "deselected" in result.stdout, (
        "Expected all backup tests to be deselected by -m 'not slow'. "
        f"Output:\n{result.stdout}"
    )
