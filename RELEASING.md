# Release Process

## Overview

Release versioning is automated.

When CI completes successfully on `main`, the release workflow:

1. inspects commits since the latest semantic tag
2. decides the next SemVer bump from conventional commits
3. creates and pushes the new `vX.Y.Z` tag
4. creates a GitHub Release from that tag
5. lets the existing publish workflow build and publish the image from the tag

The About page and runtime build metadata read the published version tag, not a
branch name.

## Version Rules

The automated bump policy is conventional-commit based:

| Commit type | Release impact |
|---|---|
| `feat` | minor |
| `fix` / `perf` | patch |
| breaking change marker (`!:` or `BREAKING CHANGE:`) | major |
| docs/chore/test-only changes | no release |

## Published Artifacts

For each release tag `vX.Y.Z`, CI publishes:

- `ghcr.io/mshirel/song-history:sha-<full-sha>`
- `ghcr.io/mshirel/song-history:X.Y.Z`
- `ghcr.io/mshirel/song-history:X.Y`

The Pi deployment should pin one of those immutable release identifiers, never
`latest`.

## Emergency Hotfixes

If the automated release path needs to be bypassed for a one-off emergency, do
so deliberately and document the reason in the commit or release notes. The
normal path remains fully automated and should be preferred.
