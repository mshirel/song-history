"""Tests for Dockerfile correctness (#102, #174)."""

from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent


class TestDependencyReproducibility:
    """A lockfile must exist and be used in the Dockerfile (#174)."""

    def test_requirements_lock_exists(self):
        """A lockfile must exist at the project root for reproducible builds."""
        lockfiles = [
            _PROJECT_ROOT / "requirements.lock",
            _PROJECT_ROOT / "requirements.txt",
            _PROJECT_ROOT / "constraints.txt",
        ]
        assert any(f.exists() for f in lockfiles), (
            "No Python dependency lockfile found. "
            "Run: pip-compile pyproject.toml --output-file requirements.lock"
        )

    def test_lockfile_is_used_in_dockerfile(self):
        """Dockerfile must reference the lockfile in its pip install step."""
        dockerfile = (_PROJECT_ROOT / "Dockerfile").read_text()
        assert any(
            lock in dockerfile
            for lock in ["requirements.lock", "requirements.txt", "constraints.txt"]
        ), "Dockerfile does not reference any lockfile — builds are non-reproducible"


class TestDockerfileCMD:
    """Verify the Dockerfile CMD is safe and meaningful."""

    @staticmethod
    def _dockerfile_content() -> str:
        dockerfile = Path(__file__).parent.parent / "Dockerfile"
        return dockerfile.read_text()

    def test_dockerfile_cmd_is_not_help(self):
        """Dockerfile CMD must not default to --help.

        A CMD of ['--help'] causes the container to print help and exit 0,
        silently hiding the fact that no service was started (#102).
        """
        content = self._dockerfile_content()
        # Everything after the last CMD instruction
        cmd_part = content.split("CMD")[-1]
        assert "--help" not in cmd_part, (
            "Dockerfile CMD must not default to --help — container would start "
            "and immediately exit without serving traffic"
        )

    def test_dockerfile_upgrades_pip(self):
        """Dockerfile must upgrade pip to clear known pip CVEs.

        pip 25.x ships with CVE-2026-1703 and CVE-2025-8869; upgrading pip
        to the latest version removes these findings from the Trivy CVE scan
        and prevents the publish CI job from failing.
        """
        content = self._dockerfile_content()
        assert "pip install" in content and "upgrade pip" in content, (
            "Dockerfile must run 'pip install --upgrade pip' to clear pip CVEs "
            "that cause the Trivy CVE scan to fail (CVE-2026-1703, CVE-2025-8869)"
        )

    def test_dockerfile_entrypoint_or_cmd_starts_web_server(self):
        """Dockerfile ENTRYPOINT+CMD combination must start the uvicorn web server.

        The production web service runs uvicorn, so the default container
        startup must invoke it so that 'docker run <image>' serves traffic (#102).
        uvicorn may appear in either ENTRYPOINT or CMD.
        """
        content = self._dockerfile_content()
        # Check both ENTRYPOINT and CMD lines together
        runtime_lines = [
            line for line in content.splitlines()
            if line.strip().startswith(("ENTRYPOINT", "CMD"))
        ]
        runtime_block = "\n".join(runtime_lines)
        assert "uvicorn" in runtime_block, (
            "Dockerfile ENTRYPOINT/CMD must start the uvicorn web server so that "
            "'docker run <image>' starts serving traffic"
        )
        assert "worship_catalog.web.app:app" in runtime_block, (
            "Dockerfile ENTRYPOINT/CMD must reference the FastAPI app module"
        )
