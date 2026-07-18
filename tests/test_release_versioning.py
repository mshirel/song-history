"""Tests for automated semantic release versioning."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

import pytest
import yaml

from worship_catalog.release import (
    determine_bump,
    next_version,
)

RELEASE_WORKFLOW_PATH = Path(".github/workflows/release.yml")
CI_WORKFLOW_PATH = Path(".github/workflows/ci.yml")


class TestReleaseVersionMath:
    """Conventional commits should drive semantic version bumps automatically."""

    def test_feat_commit_bumps_minor(self) -> None:
        assert determine_bump(["feat: add automated release tagging"]) == "minor"
        assert next_version("1.2.0", ["feat: add automated release tagging"]) == "1.3.0"

    def test_fix_commit_bumps_patch(self) -> None:
        assert determine_bump(["fix: stop using branch name for version"]) == "patch"
        assert next_version("1.2.0", ["fix: stop using branch name for version"]) == "1.2.1"

    def test_breaking_change_bumps_major(self) -> None:
        commits = ["feat!: replace manual release process", "BREAKING CHANGE: versioning"]
        assert determine_bump(commits) == "major"
        assert next_version("1.2.0", commits) == "2.0.0"

    def test_docs_only_commit_does_not_trigger_release(self) -> None:
        assert determine_bump(["docs: update release guide"]) is None
        assert next_version("1.2.0", ["docs: update release guide"]) is None


class TestRuntimeVersionMetadata:
    """The package metadata exposed at runtime should be the real release version."""

    def test_package_version_matches_distribution_metadata(self) -> None:
        import worship_catalog

        expected = importlib.metadata.version("worship-catalog")
        assert worship_catalog.__version__ == expected
        assert worship_catalog.__version__ != "0.1.0"


@pytest.mark.skipif(not RELEASE_WORKFLOW_PATH.exists(), reason="release workflow not present")
class TestReleaseWorkflow:
    """The repository should automate tag creation from main-branch pushes."""

    def test_release_workflow_exists(self) -> None:
        assert RELEASE_WORKFLOW_PATH.exists()

    def test_release_workflow_is_triggered_after_green_ci_on_main(self) -> None:
        workflow = yaml.safe_load(RELEASE_WORKFLOW_PATH.read_text())
        trigger = workflow.get("on") or workflow.get(True)
        assert trigger is not None
        trigger = trigger["workflow_run"]
        assert "CI" in trigger["workflows"]
        assert "main" in trigger["branches"]
        assert trigger["types"] == ["completed"]

    def test_release_workflow_tags_and_releases_automatically(self) -> None:
        text = RELEASE_WORKFLOW_PATH.read_text()
        assert "git tag" in text
        assert "gh release create" in text
        assert "push origin" in text


@pytest.mark.skipif(not CI_WORKFLOW_PATH.exists(), reason="ci workflow not present")
class TestPublishWorkflowVersionSource:
    """Publish builds should use release tags, not branch names, as the version source."""

    def _publish_step(self) -> dict:
        workflow = yaml.safe_load(CI_WORKFLOW_PATH.read_text())
        publish = workflow["jobs"]["publish"]
        for step in publish["steps"]:
            run_cmd = step.get("run", "")
            if "APP_VERSION" in run_cmd or step.get("id") == "version":
                return step
        raise AssertionError("Publish workflow version step not found")

    def test_publish_job_is_not_branch_versioned(self) -> None:
        workflow = yaml.safe_load(CI_WORKFLOW_PATH.read_text())
        publish = workflow["jobs"]["publish"]
        condition = publish["if"]
        assert "refs/tags/" in condition or "startsWith(github.ref, 'refs/tags/')" in condition
        assert "main" not in condition

    def test_publish_job_resolves_version_from_release_tag(self) -> None:
        text = CI_WORKFLOW_PATH.read_text()
        assert "github.ref_name" not in text or "APP_VERSION=${{ github.ref_name }}" not in text
        assert "Resolve release version" in text
        assert "steps.version.outputs.version" in text
