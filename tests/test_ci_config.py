"""Tests for CI configuration — ensure action pins and steps stay current."""

from pathlib import Path

import pytest
import yaml


CI_PATH = Path(".github/workflows/ci.yml")


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


# Known-good SHA for aquasecurity/trivy-action v0.35.0
_TRIVY_V035_SHA = "57a97c7e7821a5776cebc9bb87c984fa69cba8f1"

# SHAs for older versions that should NOT appear in CI
_STALE_TRIVY_SHAS = {
    "18f2510ee396bbf400402947b394f2dd8c87dbb0",  # v0.29.0
    "6c175e9c4083a92bbca2f9724c8a5e33bc2d97a5",  # v0.30.0
    "76071ef0d7ec797419534a183b498b4d6366cf37",  # v0.31.0
    "dc5a429b52fcf669ce959baa2c2dd26090d2a6c4",  # v0.32.0
    "f9424c10c36e288d5fa79bd3dfd1aeb2d6eae808",  # v0.33.0
    "b6643a29fecd7f34b3597bc6acb0a98b03d33ff8",  # v0.33.1
    "c1824fd6edce30d7ab345a9989de00bbd46ef284",  # v0.34.0
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
                assert sha == _TRIVY_V035_SHA, (
                    f"trivy-action SHA {sha} is unrecognised. "
                    f"Expected {_TRIVY_V035_SHA} (v0.35.0) or newer."
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
