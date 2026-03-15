# Release Process

## Prerequisites

- All changes merged to `main`
- CI passing on `main`
- `hatch-vcs` installed: `pip install hatch-vcs`

---

## Steps

### 1. Update CHANGELOG.md

Move items from `[Unreleased]` to a new version section:

```markdown
## [0.2.0] — YYYY-MM-DD

### Added
- ...

### Fixed
- ...
```

Update the comparison links at the bottom:

```markdown
[Unreleased]: https://github.com/mshirel/song-history/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/mshirel/song-history/compare/v0.1.0...v0.2.0
```

### 2. Commit CHANGELOG

```bash
git add CHANGELOG.md
git commit -m "chore: update CHANGELOG for v0.2.0"
git push origin main
```

### 3. Tag the release

```bash
git tag v0.2.0
git push origin v0.2.0
```

CI automatically triggers the `publish` job, which builds and pushes:
- `ghcr.io/mshirel/song-history:sha-<full-sha>`
- `ghcr.io/mshirel/song-history:0.2.0`
- `ghcr.io/mshirel/song-history:0.2`

### 4. Create a GitHub Release

```bash
gh release create v0.2.0 --title "v0.2.0" --notes-file <(sed -n '/## \[0.2.0\]/,/## \[/p' CHANGELOG.md | head -n -1)
```

---

## Version Numbers

This project uses [Semantic Versioning](https://semver.org/):

| Version part | When to bump |
|---|---|
| **MAJOR** (x.0.0) | Breaking CLI or API change |
| **MINOR** (0.x.0) | New feature, backwards-compatible |
| **PATCH** (0.0.x) | Bug fix, backwards-compatible |

The Python package version is derived from git tags via `hatch-vcs`.
In Docker builds where `.git` is unavailable, it falls back to `0.0.0+unknown`.
The published image tag (`:0.2.0`) is the authoritative version identifier.

---

## Hotfix Process

```bash
git checkout -b hotfix/v0.1.1 v0.1.0
# fix + test
git commit -m "fix: ..."
git tag v0.1.1
git push origin v0.1.1
```
