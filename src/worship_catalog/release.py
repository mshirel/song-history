"""Helpers for automated semantic release versioning."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

_SEMVER_RE = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)$"
)
_BREAKING_RE = re.compile(r"(^|\n)BREAKING CHANGE:", re.IGNORECASE)
_BREAKING_SUBJECT_RE = re.compile(r"^.+!:\s+")


@dataclass(frozen=True, slots=True)
class Version:
    """Semantic version components."""

    major: int
    minor: int
    patch: int

    def bump_major(self) -> Version:
        return Version(self.major + 1, 0, 0)

    def bump_minor(self) -> Version:
        return Version(self.major, self.minor + 1, 0)

    def bump_patch(self) -> Version:
        return Version(self.major, self.minor, self.patch + 1)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def parse_version(raw: str) -> Version:
    """Parse a SemVer tag or bare version string."""
    match = _SEMVER_RE.match(raw.strip())
    if not match:
        raise ValueError(f"Invalid semantic version: {raw!r}")
    return Version(
        major=int(match.group("major")),
        minor=int(match.group("minor")),
        patch=int(match.group("patch")),
    )


def determine_bump(commit_messages: Sequence[str]) -> str | None:
    """Determine the highest semantic-release bump required by commit messages.

    Returns one of ``"major"``, ``"minor"``, ``"patch"``, or ``None`` if the
    commit set does not warrant a release.
    """
    bump: str | None = None
    for message in commit_messages:
        subject = message.strip()
        if not subject:
            continue
        if _BREAKING_RE.search(subject) or _BREAKING_SUBJECT_RE.match(subject):
            return "major"
        lower = subject.lower()
        if lower.startswith("feat"):
            bump = "minor"
        elif lower.startswith(("fix", "perf")) and bump != "minor":
            bump = "patch"
    return bump


def next_version(current_version: str, commit_messages: Sequence[str]) -> str | None:
    """Return the next semantic version, or ``None`` if no release is due."""
    bump = determine_bump(commit_messages)
    if bump is None:
        return None

    version = parse_version(current_version)
    if bump == "major":
        return str(version.bump_major())
    if bump == "minor":
        return str(version.bump_minor())
    return str(version.bump_patch())


def _git_output(args: Sequence[str], repo: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def latest_release_version(repo: Path = Path(".")) -> str | None:
    """Return the latest tagged release version in a repository."""
    tags = _git_output(["tag", "--sort=-v:refname"], repo)
    for raw_tag in tags.splitlines():
        match = _SEMVER_RE.match(raw_tag.strip())
        if match:
            return f"{match.group('major')}.{match.group('minor')}.{match.group('patch')}"
    return None


def commit_messages_since_latest_release(repo: Path = Path(".")) -> list[str]:
    """Return commit subjects since the latest semver tag."""
    latest = latest_release_version(repo)
    rev_range = f"v{latest}..HEAD" if latest is not None else "HEAD"
    output = _git_output(["log", "--format=%B%x1e", rev_range], repo)
    return [entry.strip() for entry in output.split("\x1e") if entry.strip()]


def next_release_version(repo: Path = Path(".")) -> str | None:
    """Calculate the next release version from git history."""
    latest = latest_release_version(repo) or "0.0.0"
    return next_version(latest, commit_messages_since_latest_release(repo))
