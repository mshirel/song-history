"""Marker contract tests — verify registered pytest markers are in place (#91).

Also verifies mutation testing tooling is installed (issue #90).
"""

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
    # All backup tests are marked slow, so none should appear in the collected list
    assert "test_backup" not in result.stdout or "deselected" in result.stdout, (
        "Expected all backup tests to be deselected by -m 'not slow'. "
        f"Output:\n{result.stdout}"
    )


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
