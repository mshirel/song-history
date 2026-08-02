"""Tests for Dockerfile correctness (#102, #174)."""

from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent


class TestNoMaliciousFastapi:
    """The lockfile must not pin the malicious fastapi 0.136.3 (MAL-2026-4750, #458)."""

    def test_lockfile_excludes_malicious_fastapi(self):
        lock = (_PROJECT_ROOT / "uv.lock").read_text()
        assert 'name = "fastapi"\nversion = "0.136.3"' not in lock, (
            "fastapi 0.136.3 is malicious (MAL-2026-4750) — it adds an undocumented "
            "'fastar' dependency. The lockfile must pin a different version."
        )

    def test_pyproject_excludes_malicious_fastapi(self):
        pp = (_PROJECT_ROOT / "pyproject.toml").read_text()
        assert "!=0.136.3" in pp, (
            "pyproject must exclude fastapi 0.136.3 so uv can't re-pin it"
        )


class TestRuntimeImageHasNoPip:
    """pip is removed from the runtime image (#595).

    pip vendors its own dependencies under `pip/_vendor` — msgpack 1.1.2 and
    setuptools 70.3.0 at the time of writing, both carrying advisories.  They
    do not appear in `pip list` (vendored code is not an installed
    distribution) and are not in uv.lock, but they are real files in the image
    and Trivy fails the publish job on them, so nothing can ship.
    """

    def test_dockerfile_removes_pip_from_the_runtime_image(self):
        dockerfile = (_PROJECT_ROOT / "Dockerfile").read_text()
        assert "pip uninstall" in dockerfile, (
            "the runtime image must not ship pip — its vendored dependencies "
            "carry CVEs and nothing needs pip at runtime (#595)"
        )

    def test_pip_is_removed_after_dependencies_are_installed(self):
        """Removing pip before the install step would break the build."""
        lines = (_PROJECT_ROOT / "Dockerfile").read_text().splitlines()
        install_at = next(
            i for i, line in enumerate(lines) if "-r requirements.lock" in line
        )
        remove_at = next(i for i, line in enumerate(lines) if "pip uninstall" in line)
        assert install_at < remove_at, "pip must be removed only after it has installed everything"

    def test_removal_is_verified_in_the_same_layer(self):
        """A silent no-op removal would let the vendored CVEs ship anyway."""
        dockerfile = (_PROJECT_ROOT / "Dockerfile").read_text()
        assert "! command -v pip" in dockerfile, (
            "the build must assert pip is actually gone, or a failed removal "
            "ships the vulnerable vendored packages while the build stays green"
        )


class TestDependencyReproducibility:
    """A lockfile must exist and be used in the Dockerfile (#174)."""

    def test_uv_lock_exists(self):
        """The committed lockfile must exist at the project root for reproducible builds.

        requirements.lock is a generated export of uv.lock (#589) and is not
        committed, so uv.lock is the file that must be present.
        """
        assert (_PROJECT_ROOT / "uv.lock").exists(), (
            "No committed Python lockfile found — builds are non-reproducible. "
            "uv.lock is the sole resolution authority (#546)."
        )

    def test_lockfile_is_used_in_dockerfile(self):
        """Dockerfile must reference the lockfile in its pip install step."""
        dockerfile = (_PROJECT_ROOT / "Dockerfile").read_text()
        assert any(
            lock in dockerfile
            for lock in ["requirements.lock", "requirements.txt", "constraints.txt"]
        ), "Dockerfile does not reference any lockfile — builds are non-reproducible"


class TestDockerfileHealthcheck:
    """The image must define a HEALTHCHECK so non-compose deploys have a probe (#402)."""

    def test_dockerfile_has_healthcheck(self):
        dockerfile = (_PROJECT_ROOT / "Dockerfile").read_text()
        assert "HEALTHCHECK" in dockerfile, (
            "Dockerfile must define a HEALTHCHECK so standalone 'docker run' "
            "invocations (not using the compose healthcheck) detect a dead process."
        )

    def test_healthcheck_targets_health_endpoint(self):
        dockerfile = (_PROJECT_ROOT / "Dockerfile").read_text()
        idx = dockerfile.find("HEALTHCHECK")
        assert idx != -1
        assert "/health" in dockerfile[idx:], "HEALTHCHECK must probe the /health endpoint"

    def test_healthcheck_interval_reasonable(self):
        import re

        dockerfile = (_PROJECT_ROOT / "Dockerfile").read_text()
        m = re.search(r"--interval=(\d+)s", dockerfile)
        assert m, "HEALTHCHECK must set an explicit --interval"
        assert int(m.group(1)) <= 60, "HEALTHCHECK interval should be <= 60s"


class TestDockerfilePythonVersion:
    """The base image must use a GA (non-pre-release) Python version (#403)."""

    def test_dockerfile_uses_stable_python(self):
        """Dockerfile base image must use a GA (non-pre-release) Python version.

        Python 3.14 was pre-release as of 2026-05-25; GA versions are <= 3.13.
        pyproject.toml targets 3.10 and CI runs on 3.12, so production must not
        run an untested pre-release interpreter.
        """
        import re

        dockerfile = (_PROJECT_ROOT / "Dockerfile").read_text()
        m = re.search(r"FROM python:(\d+)\.(\d+)", dockerfile)
        assert m, "Could not find a 'FROM python:X.Y' line in the Dockerfile"
        major, minor = int(m.group(1)), int(m.group(2))
        assert (major, minor) <= (3, 13), (
            f"Dockerfile uses Python {major}.{minor} which is pre-release. "
            "Use a GA Python version (e.g., 3.12 or 3.13)."
        )


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
