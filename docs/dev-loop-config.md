# Dev loop config

Read at preflight by the `dev-loop` skill. **Every command here runs verbatim.** Keep it versioned
with the code: when a test or deploy command changes, this file changes in the same PR.

Review thresholds and lenses are **not** duplicated here — they live in
[`docs/code-review-config.md`](code-review-config.md).

---

## Batch

```yaml
batch_source: milestone
default_label: ""
concurrency: 1
max_attempts: 2
```

`concurrency: 1` is deliberate. The publish pipeline is a single shared path (one GHCR tag stream,
one Pi), and cards in this repo routinely touch `ci.yml` — two in flight at once produce merge
conflicts in the same workflow file and races on the image tag.

## Setup — once per worktree

```yaml
setup:
  - uv sync --frozen --extra dev --extra web --extra ocr
```

`--frozen` matters: `uv.lock` is the sole resolution authority (#546), and a loop that silently
re-resolves would land a lockfile change inside an unrelated card.

## Validate — the deterministic gauntlet

Ordered cheapest-first. Mirrors what CI enforces, so a green gauntlet predicts a green PR.

```yaml
validate:
  - uv run --frozen ruff check src/
  - uv run --frozen mypy src/
  - uv run --frozen pytest -q
```

Notes that save a wake:

- **Lint `src/` only.** CI runs `ruff check src/`; `tests/` has a large pre-existing violation
  backlog (unsorted imports, `B008`, long lines). `ruff check .` returns hundreds of findings that
  are not yours and will send you chasing noise.
- **The suite has a floor, not just a pass/fail.** CI fails if fewer than 950 tests pass, and
  separately if fewer than 5 `integration and not slow` tests pass — a deleted test file cannot
  slip through as "green".

## Mandatory suites — path triggers

The coupled tests a focused diff would otherwise skip.

```yaml
mandatory_suites:
  - when: ".github/workflows/**"
    run:
      - uv run --frozen pytest tests/test_ci_config.py tests/test_release_versioning.py
  - when: "Dockerfile"
    run:
      - uv run --frozen pytest tests/test_dockerfile.py tests/test_ci_config.py
  - when: "pyproject.toml"
    run:
      - uv run --frozen pytest tests/test_ci_config.py tests/test_dockerfile.py
  - when: "uv.lock"
    run:
      - uv run --frozen pytest tests/test_dockerfile.py
  - when: "src/worship_catalog/web/**"
    run:
      - uv run --frozen pytest tests/test_web.py tests/test_web_security.py tests/test_accessibility.py
  - when: "src/worship_catalog/db.py"
    run:
      - uv run --frozen pytest tests/test_db_integration.py
  - when: "scripts/**"
    run:
      - uv run --frozen pytest tests/test_scripts.bats tests/test_backup_sh.py
  - when: "deploy/pi/**"
    run:
      - uv run --frozen pytest tests/test_ci_config.py
```

`pyproject.toml` and `uv.lock` trigger the Dockerfile suite because the runtime image installs an
export of `uv.lock`, so a dependency edit changes what ships.

## Review

```yaml
review:
  skill: adversarial-pr-review
  config: docs/code-review-config.md
  always: false
  routing: standing-rule-12
```

Repo-specific routing additions — treat these as routing rows even when validation is green:

- **`Dockerfile` or the `publish` job** — changes the artifact that reaches the public internet, and
  PR CI cannot exercise it (see traps).
- **`.github/workflows/*.yml` permission blocks** — a `permissions:` change is an auth change.
- **`deploy/pi/**`** — the production host config.

## Merge

```yaml
merge:
  strategy: rebase
  protected_main: true
  delete_branch: true
  require_ci_green: true
  ci_watch: gh run watch <id> --exit-status
```

`main` is protected by an **active ruleset** (`pull_request`, `required_status_checks`, `deletion`,
`non_fast_forward`) with **no bypass actors**. A refspec push to `main` is rejected — a PR is
mandatory, and it must be merged server-side. Branch protection also requires the head to be up to
date, so `gh pr update-branch <N>` before merging is routine, not an error.

Required checks: `test`, `e2e`, `security`, CodeQL. `publish` reports `skipping` on PRs — that is
correct, not a failure.

## Batch close

Merging is not shipping. The Pi runs a digest-pinned image; nothing reaches it until an image is
built *and* the pin is updated *and* the stack is rolled.

```yaml
batch_close:
  deploy:
    # 1. Build and publish from main. `publish` does NOT run on branch pushes, so this
    #    manual dispatch is the only path that produces an image outside a release tag.
    - gh workflow run ci.yml --ref main
    - gh run watch <id> --exit-status
    # 2. Capture the published tag + digest from the run log.
    - gh run view <id> --log | grep -oE 'sha-[a-f0-9]{40}@sha256:[a-f0-9]{64}'
    # 3. Pin it in deploy/pi/docker-compose.yml (both `watcher` and `song-history`
    #    services) on a branch, and land it as a PR like any other change.
    # 4. Roll the Pi. Back up the live file first; app services only — leaving
    #    traefik/cloudflared untouched avoids dropping the public tunnel.
    - ssh pi-songs 'sudo cp -p /opt/song-history/docker-compose.yml /opt/song-history/docker-compose.yml.bak-pre-<sha>-$(date +%Y%m%d-%H%M%S)'
    - scp deploy/pi/docker-compose.yml pi-songs:/tmp/dc-new.yml
    - ssh pi-songs 'sudo install -o songs -g songs -m 644 /tmp/dc-new.yml /opt/song-history/docker-compose.yml && rm -f /tmp/dc-new.yml'
    - ssh pi-songs 'cd /opt/song-history && sudo docker compose config -q'
    - ssh pi-songs 'cd /opt/song-history && sudo docker compose pull song-history watcher'
    - ssh pi-songs 'cd /opt/song-history && sudo docker compose up -d song-history watcher'
  verify:
    # Each check must look DIFFERENT if the deploy had not happened.
    - ssh pi-songs 'cd /opt/song-history && sudo docker compose ps --format "{{.Name}}\t{{.Image}}\t{{.Status}}"'
      # the running digest must equal the one just published, and status must read (healthy)
    - curl -s -o /dev/null -w '%{http_code}' https://songs.highland-coc.com/health   # expect 200
    - curl -s -o /dev/null -w '%{http_code}' https://songs.highland-coc.com/reports  # expect 200
    # plus at least one property THIS batch changed, observed in prod — not a generic 200.
  then:
    - close the milestone
    - post the summary to the notify channel
    - ScheduleWakeup stop:true
```

Deploy access: files under `/opt/song-history` are owned by `songs:songs` and `.env` is not
world-readable (#446), so compose commands need `sudo`. `matt` has passwordless sudo and is in the
`docker` group. There is **no systemd unit** for the app stack — it is plain `docker compose` with
`restart: unless-stopped`.

## Notify

```yaml
notify:
  skill: telegram
  channel: claude-ops
  on: [batch_start, card_landed, card_parked, batch_close, escalation]
```

`claude-ops` (`@Tanx_Automation_Claude_bot`), not the default `highland-espn` channel — that stream
is for the ESPN fantasy football connector.

## Repo-specific traps

Each of these has cost a wake or would have. One line, plus how to tell environmental from real.

- **11 tests fail on any host without the `sqlite3` CLI.** `tests/test_backup_sh.py`,
  `tests/test_backup_restore.py`, `tests/test_seed_pi_db_sh.py` shell out to `sqlite3` and report
  `FAIL: integrity check failed`. CI has the binary; the WSL/vm-ai-dev workstations do not. Baseline
  is **1417 passed, 11 failed**. To tell environmental from real: run the same file in the canonical
  checkout on `main` — identical failures mean it is the host, not your diff. Never "fix" these.

- **`publish` never runs on a PR.** Its gate is `refs/tags/v*` / `schedule` / `workflow_dispatch`,
  so PR CI never builds the Docker image, never runs Trivy, and never runs the smoke test. A card
  touching `Dockerfile` or the `publish` job is **not validated by a green PR**. Exercise it with
  `gh workflow run ci.yml --ref <your-branch>` and read the `publish` job before merging. This is
  how #595 (Trivy blocking every push) went unnoticed for days.

- **`requirements.lock` is generated, not committed** (#589). A fresh worktree does not have it, and
  `docker build` / `docker compose build` will fail at `COPY requirements.lock` until you run
  `make lockfile`. `make build` does it for you.

- **`loop-board` needs the full slug.** The local directory is `highland/song-history`, so
  `--repo song-history` fails to resolve and prints an empty ready queue with a `jq` error — which
  reads exactly like "batch complete". Always
  `loop-board --repo mshirel/song-history --milestone "<title>"`.

- **The weekly scheduled rebuild fails silently** (#598). Do not treat "no failure notification" as
  evidence the image is current; check `gh run list --workflow=ci.yml --event=schedule`.

- **`graphify-out/` is gitignored and local-only.** Never `git add -f` it. Run `graphify update .`
  after code changes to keep the local index fresh.
