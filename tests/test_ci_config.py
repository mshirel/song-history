"""Tests for CI configuration — ensure action pins and steps stay current."""

from pathlib import Path

import pytest
import yaml

CI_PATH = Path(".github/workflows/ci.yml")
DEPENDABOT_PATH = Path(".github/dependabot.yml")
PYPROJECT_PATH = Path("pyproject.toml")
REQUIREMENTS_LOCK_PATH = Path("requirements.lock")

# The set of valid Dependabot package-ecosystem values.  "docker-compose" is
# deliberately absent — it is NOT a valid ecosystem; the "docker" ecosystem
# scans both Dockerfiles and docker-compose.yml files (#502).
_VALID_DEPENDABOT_ECOSYSTEMS = {
    "pip",
    "github-actions",
    "docker",
    "npm",
    "gomod",
    "bundler",
    "cargo",
    "composer",
    "nuget",
    "gitsubmodule",
    "terraform",
    "gradle",
    "maven",
    "pub",
    "mix",
    "devcontainers",
    "uv",
}


@pytest.mark.skipif(not DEPENDABOT_PATH.exists(), reason="Dependabot config not present")
class TestDependabotEcosystems:
    """Every Dependabot ecosystem must be valid, and the Pi deploy stack images
    must be covered by a real "docker" entry — not the invalid "docker-compose"
    ecosystem that Dependabot silently ignores (#502)."""

    def _updates(self) -> list[dict]:
        cfg = yaml.safe_load(DEPENDABOT_PATH.read_text())
        return cfg["updates"]

    def test_no_docker_compose_ecosystem(self) -> None:
        """'docker-compose' is not a valid Dependabot ecosystem and must not appear."""
        ecos = [u["package-ecosystem"] for u in self._updates()]
        assert "docker-compose" not in ecos, (
            "'docker-compose' is not a valid Dependabot package-ecosystem — "
            "Dependabot silently ignores it. Use 'docker' instead (#502)."
        )

    def test_all_ecosystems_valid(self) -> None:
        """Every package-ecosystem entry must be a recognised Dependabot value."""
        ecos = [u["package-ecosystem"] for u in self._updates()]
        invalid = [e for e in ecos if e not in _VALID_DEPENDABOT_ECOSYSTEMS]
        assert not invalid, (
            f"Invalid Dependabot package-ecosystem value(s): {invalid}. "
            f"Valid values: {sorted(_VALID_DEPENDABOT_ECOSYSTEMS)}"
        )

    def test_deploy_pi_covered_by_docker_ecosystem(self) -> None:
        """The Pi deploy stack (/deploy/pi) must have a 'docker' update entry so
        traefik/promtail/cloudflared receive digest-bump PRs (#502)."""
        assert any(
            u["package-ecosystem"] == "docker"
            and u["directory"] in ("/deploy/pi", "/deploy/pi/")
            for u in self._updates()
        ), (
            "No 'docker' Dependabot entry for '/deploy/pi' — the production Pi "
            "stack images (traefik, promtail, cloudflared) get no update PRs."
        )

    def test_python_updates_follow_uv_lockfile(self) -> None:
        """Dependabot must update the authoritative uv lock, not resolve with pip."""
        root_python_entries = [
            update
            for update in self._updates()
            if update["directory"] == "/"
            and update["package-ecosystem"] in {"pip", "uv"}
        ]
        assert [entry["package-ecosystem"] for entry in root_python_entries] == ["uv"], (
            "Python dependencies must use the uv Dependabot ecosystem so uv.lock "
            "remains the sole resolution authority"
        )


@pytest.mark.skipif(not CI_PATH.exists(), reason="CI config not present")
class TestDependencyLockAuthority:
    """CI and deployment artifacts must consume one frozen uv dependency graph (#546)."""

    def test_web_extra_declares_itsdangerous_directly(self) -> None:
        """The web code imports itsdangerous, so the web extra must declare it (#542)."""
        try:
            import tomllib
        except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
            import tomli as tomllib

        project = tomllib.loads(PYPROJECT_PATH.read_text())["project"]
        web_dependencies = project["optional-dependencies"]["web"]
        assert any(dep.startswith("itsdangerous") for dep in web_dependencies), (
            "itsdangerous is imported by the web package and must be a direct web dependency"
        )

    def test_ci_installs_one_frozen_uv_environment(self) -> None:
        ci = CI_PATH.read_text()
        expected = "uv sync --frozen --extra dev --extra web --extra ocr"
        assert ci.count(expected) >= 3, (
            "test, e2e, and security jobs must install the same frozen uv graph"
        )
        assert "pip install -r requirements.lock" not in ci
        assert 'pip install -e ".[dev]"' not in ci

    def test_ci_validates_lock_without_reresolving(self) -> None:
        ci = CI_PATH.read_text()
        assert "uv lock --check" in ci
        assert "uv export --frozen" in ci
        assert "pip-compile" not in ci, (
            "pip-compile independently resolves dependencies and must not be a lock validator"
        )

    def test_deployment_lock_identifies_uv_as_generator(self) -> None:
        header = "\n".join(REQUIREMENTS_LOCK_PATH.read_text().splitlines()[:8])
        assert "uv export" in header, (
            "requirements.lock must be a frozen export from uv.lock, not an independent lock"
        )


@pytest.mark.skipif(not CI_PATH.exists(), reason="CI config not present")
class TestIntegrationTestStep:
    """CI integration test step must enforce a minimum test count."""

    def test_integration_step_exists(self) -> None:
        """The CI workflow must have an integration test step."""
        content = CI_PATH.read_text()
        assert "integration and not slow" in content, (
            "Integration test step not found in ci.yml"
        )

    def test_integration_step_uses_minimum_count(self) -> None:
        """The integration test step must check that enough tests ran."""
        workflow = yaml.safe_load(CI_PATH.read_text())
        test_job = workflow["jobs"]["test"]
        steps = test_job["steps"]

        # Find the integration test step by name
        integration_step = None
        for step in steps:
            run_cmd = step.get("run", "")
            if "integration and not slow" in run_cmd:
                integration_step = step
                break

        assert integration_step is not None, (
            "Integration test step not found in ci.yml"
        )

        run_block = integration_step["run"]

        has_count_check = any(
            keyword in run_block.lower()
            for keyword in ["passed", "-lt", "minimum", "at least"]
        )
        assert has_count_check, (
            "Integration test step has no minimum test count assertion — "
            "if all integration tests disappear, CI will pass silently"
        )


# Minimum acceptable floor for the main test step (#409).  The suite has
# 1100+ tests; a floor of 700 left ~400 tests of slack, so whole test files
# could vanish without CI noticing.  Keep this in step with the suite size.
_MAIN_TEST_FLOOR_MINIMUM = 950


@pytest.mark.skipif(not CI_PATH.exists(), reason="CI config not present")
class TestMainTestStepFloor:
    """The main test step's pass-count floor must reflect the real suite size (#409)."""

    def _main_test_run_block(self) -> str:
        workflow = yaml.safe_load(CI_PATH.read_text())
        steps = workflow["jobs"]["test"]["steps"]
        for step in steps:
            run_cmd = step.get("run", "")
            # The main test step runs coverage and has a passed-count floor,
            # distinct from the integration step (which filters by marker).
            if "--cov" in run_cmd and "integration and not slow" not in run_cmd:
                return run_cmd
        raise AssertionError("Main test step (with --cov) not found in ci.yml")

    def test_main_step_has_passed_count_floor(self) -> None:
        """The main test step must assert a minimum number of passed tests."""
        run_block = self._main_test_run_block()
        assert "-lt" in run_block and "passed" in run_block.lower(), (
            "Main test step has no passed-count floor — whole test files could "
            "be deleted and CI would still pass."
        )

    def test_main_step_floor_is_current(self) -> None:
        """The floor must be >= the agreed minimum, not the stale value of 700."""
        import re

        run_block = self._main_test_run_block()
        floors = [int(n) for n in re.findall(r"-lt (\d+)", run_block)]
        assert floors, "No '-lt <N>' floor comparison found in the main test step"
        floor = max(floors)
        assert floor >= _MAIN_TEST_FLOOR_MINIMUM, (
            f"Main test-count floor is {floor}; expected >= "
            f"{_MAIN_TEST_FLOOR_MINIMUM}. The suite has 1100+ tests — a low floor "
            "defeats the purpose of the guard."
        )


@pytest.mark.skipif(not CI_PATH.exists(), reason="CI config not present")
class TestSmokeTestCsrf:
    """The publish smoke test runs the production image, which now hard-requires
    CSRF_SECRET (#406). The step must supply CSRF_SECRET (or TESTING) or the
    container exits at startup and the image is never pushed."""

    def _smoke_run_block(self) -> str:
        workflow = yaml.safe_load(CI_PATH.read_text())
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                if step.get("name", "").lower().startswith("smoke test"):
                    return step.get("run", "")
        raise AssertionError("Smoke test step not found in ci.yml")

    def test_smoke_test_provides_csrf_config(self) -> None:
        run_block = self._smoke_run_block()
        assert "CSRF_SECRET" in run_block or "TESTING" in run_block, (
            "Smoke test must pass CSRF_SECRET (or TESTING=1) to the container; "
            "otherwise #406 enforcement makes the image exit at startup and the "
            "publish push is skipped."
        )


@pytest.mark.skipif(not CI_PATH.exists(), reason="CI config not present")
class TestSmokeTestRealRoute:
    """The publish smoke test must exercise a real rendered route and a report
    route, not just /health (#515). /health returns a static OK without touching
    templates, the DB query paths, or a router, so a broken Jinja template or an
    unregistered router would boot healthy and pass — the very failures the
    smoke test on the real artifact should catch before the multi-platform push."""

    def _smoke_run_block(self) -> str:
        workflow = yaml.safe_load(CI_PATH.read_text())
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                if step.get("name", "").lower().startswith("smoke test"):
                    return step.get("run", "")
        raise AssertionError("Smoke test step not found in ci.yml")

    def test_smoke_test_hits_more_than_health(self) -> None:
        run_block = self._smoke_run_block()
        # It must still probe /health for readiness, but must not stop there.
        assert "/health" in run_block, "Smoke test should still probe /health"
        assert "/songs" in run_block, (
            "Smoke test must hit the /songs rendered route so a broken template "
            "or router regression fails before the multi-platform push (#515)."
        )

    def test_smoke_test_asserts_rendered_songs_page(self) -> None:
        run_block = self._smoke_run_block()
        # Assert the songs route is checked for real rendered markup (not just a
        # 200). The smoke DB is empty, so we match the page heading rather than
        # a <table>, but either proves the template rendered.
        assert "curl -sf" in run_block and "/songs" in run_block, (
            "Smoke test must fetch /songs and grep its rendered HTML."
        )
        assert "grep" in run_block, (
            "Smoke test must grep the /songs response for rendered markup, "
            "not just check the HTTP status."
        )

    def test_smoke_test_hits_a_report_route(self) -> None:
        run_block = self._smoke_run_block()
        assert "/reports" in run_block, (
            "Smoke test must exercise a report route (GET /reports render or a "
            "CSRF-protected POST /reports/ccli) so a router regression is caught "
            "before the push (#515)."
        )

    def test_smoke_test_ccli_post_accepts_csrf_status(self) -> None:
        run_block = self._smoke_run_block()
        assert "/reports/ccli" in run_block, (
            "Smoke test must POST to /reports/ccli to prove the report router + "
            "CSRF middleware are wired."
        )
        # A CSRF-protected POST returns 403; 200 is tolerated if CSRF is relaxed.
        assert "403" in run_block, (
            "Smoke test must accept the 403 that a CSRF-protected POST returns — "
            "that status still proves the router + middleware are registered."
        )


@pytest.mark.skipif(not CI_PATH.exists(), reason="CI config not present")
class TestCveSkipReviewNote:
    """Every pip-audit CVE ignore must carry a re-evaluation note so suppressed
    vulnerabilities don't become a permanent ratchet (#408)."""

    def test_cve_skips_have_review_note(self) -> None:
        import re

        ci = CI_PATH.read_text()
        skips = re.findall(r"--ignore-vuln\s+(CVE-\d{4}-\d+)", ci)
        # If there are no skips, there's nothing to review — trivially fine.
        for cve in skips:
            idx = ci.index(cve)
            surrounding = ci[max(0, idx - 300):idx + 100].lower()
            assert "re-evaluate" in surrounding or "review" in surrounding, (
                f"CVE skip for {cve} has no re-evaluation note. Add a comment "
                "stating when to remove it (e.g. 'Re-evaluate when pip >= X.Y ships')."
            )


# Known-good SHA for aquasecurity/trivy-action v0.36.0
_TRIVY_CURRENT_SHA = "ed142fd0673e97e23eac54620cfb913e5ce36c25"

# SHAs for older versions that should NOT appear in CI
_STALE_TRIVY_SHAS = {
    "18f2510ee396bbf400402947b394f2dd8c87dbb0",  # v0.29.0
    "6c175e9c4083a92bbca2f9724c8a5e33bc2d97a5",  # v0.30.0
    "76071ef0d7ec797419534a183b498b4d6366cf37",  # v0.31.0
    "dc5a429b52fcf669ce959baa2c2dd26090d2a6c4",  # v0.32.0
    "f9424c10c36e288d5fa79bd3dfd1aeb2d6eae808",  # v0.33.0
    "b6643a29fecd7f34b3597bc6acb0a98b03d33ff8",  # v0.33.1
    "c1824fd6edce30d7ab345a9989de00bbd46ef284",  # v0.34.0
    "57a97c7e7821a5776cebc9bb87c984fa69cba8f1",  # v0.35.0
}


@pytest.mark.skipif(not CI_PATH.exists(), reason="CI config not present")
class TestTrivyActionVersion:
    """Trivy action should be pinned to a current release."""

    def test_trivy_action_pin_is_current(self) -> None:
        content = CI_PATH.read_text()
        for line in content.splitlines():
            if "aquasecurity/trivy-action@" in line:
                sha = line.split("aquasecurity/trivy-action@")[1].split()[0]
                assert sha not in _STALE_TRIVY_SHAS, (
                    f"trivy-action is pinned to a stale SHA ({sha}). "
                    "Bump to the latest release."
                )
                assert sha == _TRIVY_CURRENT_SHA, (
                    f"trivy-action SHA {sha} is unrecognised. "
                    f"Expected {_TRIVY_CURRENT_SHA} (v0.36.0) or newer."
                )
                return
        pytest.fail("aquasecurity/trivy-action not found in CI config")

    def test_trivy_action_has_version_comment(self) -> None:
        content = CI_PATH.read_text()
        for line in content.splitlines():
            if "aquasecurity/trivy-action@" in line:
                assert "# v" in line, (
                    "trivy-action pin should have a version comment "
                    "(e.g. '# v0.35.0') for maintainability"
                )
                return
        pytest.fail("aquasecurity/trivy-action not found in CI config")
