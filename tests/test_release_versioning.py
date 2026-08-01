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


@pytest.mark.skipif(not RELEASE_WORKFLOW_PATH.exists(), reason="release workflow not present")
class TestReleaseTriggersPublish:
    """A cut release must actually build and push a container image (#583).

    `release.yml` tags with the default GITHUB_TOKEN, and GitHub deliberately
    does not trigger workflows from GITHUB_TOKEN-created events.  So the tag
    push fires nothing, `publish` never runs on `refs/tags/v*`, and the release
    ships no image — v1.3.1 was cut with no container.  The workflow must
    therefore dispatch CI itself for the new tag.
    """

    def _release_steps(self) -> list[dict]:
        return yaml.safe_load(RELEASE_WORKFLOW_PATH.read_text())["jobs"]["release"]["steps"]

    def _dispatch_step(self) -> dict | None:
        for step in self._release_steps():
            if "workflow run" in step.get("run", "").replace("gh workflow run", "workflow run"):
                return step
        return None

    def test_release_dispatches_ci_for_the_new_tag(self) -> None:
        step = self._dispatch_step()
        assert step is not None, (
            "release.yml must dispatch ci.yml for the tag it just created — a "
            "GITHUB_TOKEN tag push triggers no workflow, so nothing builds the image (#583)"
        )
        run = step["run"]
        assert "ci.yml" in run, "the dispatch must target the CI workflow that owns `publish`"
        assert "--ref" in run and "steps.version.outputs.version" in run, (
            "the dispatch must target the newly created tag ref, not a branch"
        )

    def test_dispatch_runs_only_when_a_release_was_cut(self) -> None:
        step = self._dispatch_step()
        assert step is not None
        assert step.get("if") == "steps.version.outputs.release == 'true'", (
            "dispatching CI when no tag was cut would rebuild main under a bogus version"
        )

    def test_dispatch_happens_after_the_tag_exists(self) -> None:
        """Dispatching a ref that has not been pushed yet fails with 'no ref found'."""
        steps = self._release_steps()
        tag_at = next(i for i, s in enumerate(steps) if "git tag" in s.get("run", ""))
        dispatch_at = next(
            i for i, s in enumerate(steps) if "gh workflow run" in s.get("run", "")
        )
        assert tag_at < dispatch_at, "the tag must be pushed before CI is dispatched for it"

    def test_dispatch_is_the_last_step(self) -> None:
        """A dispatch failure must not suppress the GitHub Release.

        The tag is already pushed by then, so if the Release step never runs the
        version is stranded for good: the next run computes an empty
        `v<new>..HEAD` range, resolves release=false, and never retries.
        """
        steps = self._release_steps()
        release_at = next(
            i for i, s in enumerate(steps) if "gh release create" in s.get("run", "")
        )
        dispatch_at = next(
            i for i, s in enumerate(steps) if "gh workflow run" in s.get("run", "")
        )
        assert release_at < dispatch_at, (
            "publish the GitHub Release before dispatching CI, so a dispatch "
            "failure leaves only the image missing and recoverable by hand"
        )

    def test_job_requires_first_party_provenance(self) -> None:
        """`workflow_run` alone would run untrusted fork code with a write token.

        The `branches:` filter matches the *triggering run's* head branch, so a
        fork PR raised from a branch named `main` passes it — and this job
        checks out that run's head_sha and executes it.
        """
        condition = yaml.safe_load(RELEASE_WORKFLOW_PATH.read_text())["jobs"]["release"]["if"]
        assert "workflow_run.event == 'push'" in condition, (
            "only a push-triggered CI run may cut a release; a pull_request run "
            "carries untrusted code"
        )
        assert "head_repository.full_name == github.repository" in condition, (
            "only a first-party run may cut a release — a fork's head_sha must "
            "never be checked out into a job with contents/actions write"
        )

    def test_workflow_has_permission_to_dispatch(self) -> None:
        workflow = yaml.safe_load(RELEASE_WORKFLOW_PATH.read_text())
        permissions = workflow.get("permissions", {})
        assert permissions.get("actions") == "write", (
            "`gh workflow run` needs actions: write; without it the dispatch 403s "
            "and the release silently ships no image again (#583)"
        )


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
