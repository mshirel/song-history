# tests/test_ci_config.py

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

        # The run block must contain an explicit minimum count check.
        # A bare `pytest -m ...` exits 0 even when zero tests match,
        # so we need a post-run assertion that enough tests passed.
        has_count_check = any(
            keyword in run_block.lower()
            for keyword in ["passed", "-lt", "minimum", "at least"]
        )
        assert has_count_check, (
            "Integration test step has no minimum test count assertion — "
            "if all integration tests disappear, CI will pass silently"
        )
