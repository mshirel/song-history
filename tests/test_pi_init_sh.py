"""Tests for deploy/pi/init.sh — acme.json permission validation (#65)."""

import os
import subprocess
from pathlib import Path

import pytest

INIT_SCRIPT = Path(__file__).parent.parent / "deploy" / "pi" / "init.sh"


def run_init(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(INIT_SCRIPT)],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
    )


@pytest.mark.slow
class TestInitShAcmePermissions:
    """deploy/pi/init.sh validates acme.json permissions before starting."""

    def test_init_sh_exists(self) -> None:
        """deploy/pi/init.sh must exist."""
        assert INIT_SCRIPT.exists(), f"{INIT_SCRIPT} does not exist"

    def test_init_sh_fails_when_acme_json_has_wrong_permissions(
        self, tmp_path: Path
    ) -> None:
        """init.sh must exit non-zero when acme.json has permissions other than 600."""
        acme = tmp_path / "acme.json"
        acme.write_text("{}")
        acme.chmod(0o644)
        result = run_init({"ACME_DIR": str(tmp_path)})
        assert result.returncode != 0, (
            "init.sh should fail when acme.json has wrong permissions"
        )
        assert b"600" in result.stderr.encode() or "600" in result.stderr, (
            "Error message must mention the required permissions (600)"
        )

    def test_init_sh_passes_when_acme_json_has_correct_permissions(
        self, tmp_path: Path
    ) -> None:
        """init.sh must exit 0 when acme.json has permissions 600."""
        acme = tmp_path / "acme.json"
        acme.write_text("{}")
        acme.chmod(0o600)
        result = run_init({"ACME_DIR": str(tmp_path)})
        assert result.returncode == 0, (
            f"init.sh should pass when acme.json has correct permissions\n"
            f"stderr: {result.stderr}"
        )

    def test_init_sh_passes_when_acme_json_is_absent(self, tmp_path: Path) -> None:
        """init.sh must exit 0 when acme.json does not yet exist (first run)."""
        result = run_init({"ACME_DIR": str(tmp_path)})
        assert result.returncode == 0, (
            f"init.sh should pass when acme.json is absent (first-run scenario)\n"
            f"stderr: {result.stderr}"
        )

    def test_init_sh_stderr_mentions_chmod_fix(self, tmp_path: Path) -> None:
        """Error message must include the chmod 600 fix command."""
        acme = tmp_path / "acme.json"
        acme.write_text("{}")
        acme.chmod(0o644)
        result = run_init({"ACME_DIR": str(tmp_path)})
        assert "chmod" in result.stderr, (
            "Error message must include 'chmod' to guide the operator"
        )
