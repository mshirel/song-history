# Code Review Config — song-history (highland / worship-catalog)

Project-specific guidance for the portable `full-code-review` skill (`~/.claude/skills/full-code-review`).
The skill carries no project knowledge; it reads this file. This project is the original reference
deployment for the skill (the pi-songs host review pattern originated here).

## Project identity & stack

- **What it is:** Python/FastAPI **public web app** — a worship-song catalog. Imports PPTX service
  decks, tracks songs/services/leaders, and produces CCLI/usage reports for a church.
- **Language/framework:** Python, FastAPI, **HTMX** front-end, **SQLite**, Playwright for E2E.
  `uv` deps, `src/` layout (`src/worship_catalog/`), Ruff 100-char, pytest markers
  (`unit`, `integration`, `slow`, `e2e`).
- **Entry points:** `src/worship_catalog/web/app.py` (web routes), `src/worship_catalog/cli.py` (CLI).
- **Runtime shape:** Docker Compose on **pi-songs**, served publicly at `songs.highland-coc.com`
  via a **cloudflared tunnel** (+ Traefik). Public internet exposure → runtime host posture is part
  of the attack surface.

## Applicability  (which agent groups / personas apply)

| Agent group | Applies? | Notes |
|---|---|---|
| A — App correctness (Architect, Developer, Database/Data) | **yes** | SQLite concurrency is a live concern (background import threads + web requests). |
| B — Platform & supply chain (DevOps, DevSecOps, Security) | **yes** | **Includes the live pi-songs host review** (below) — public tunnel makes it mandatory. |
| C — Frontend & UX (Product Manager, UAT, Accessibility) | **yes** | Real browser app with HTMX — UAT (Playwright) and Accessibility (WCAG 2.1 AA) both fully apply. |
| D — QA / test strategy | **yes** | Markers defined; verify they're used and integration tests don't silently skip. |

All ten personas apply here — this is the full-coverage reference project.

## Deployment host & read-only host review  — MANDATORY

`songs.highland-coc.com` is exposed to the internet via a cloudflared tunnel, so a code-only review
is incomplete. **SSH into pi-songs and run read-only checks every review** (`ssh pi-songs` — see
`~/.ssh/config`; passwordless sudo + docker group available). **Never change host state during a
review** — file findings as issues instead. The DevOps lens emphasizes reliability/operability of
these findings; the Security lens emphasizes attack surface — but the inspection happens once.

```bash
# Listening sockets / interface binding — flag app/admin ports on 0.0.0.0 that should be
# loopback/internal-only and bypass Cloudflare/Traefik (e.g. :8000 app+/metrics, node_exporter
# :9100, cloudflared metrics :2000)
sudo ss -tlnp

# Host firewall — flag an inactive firewall on an internet-facing host
sudo ufw status verbose
sudo iptables -S        # and/or: sudo nft list ruleset

# Secret-at-rest perms — must be 600 (CF API token, tunnel token, CSRF secret, upload password)
stat -c '%a %U:%G %n' /opt/song-history/.env traefik/acme.json

# SSH hardening — flag password auth enabled / no fail2ban
sudo sshd -T | grep -E 'passwordauthentication|permitrootlogin'
systemctl is-active fail2ban

# Container privileges — flag root/privileged/extra-caps and docker.sock mounts (per service)
docker inspect <cid> --format 'User={{.Config.User}} Priv={{.HostConfig.Privileged}} CapAdd={{.HostConfig.CapAdd}}'

# Runtime image pinning — third-party images (cloudflared, promtail, traefik) must be digest-pinned
docker compose images

# Effective runtime env vs. exposure — TRUSTED_PROXY must be set (per-client rate limiting behind
# the tunnel), plus HTTPS_ONLY, CSRF_SECRET, UPLOAD_PASSWORD
docker compose exec song-history printenv TRUSTED_PROXY HTTPS_ONLY CSRF_SECRET UPLOAD_PASSWORD

# What's reachable unauthenticated — flag sensitive endpoints; reason about tunnel forwarding
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/metrics
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/jobs

# OS patch level + Docker version
cat /etc/os-release; uname -r; apt-get -s upgrade | grep -c security
```

- **Runbook to cross-reference:** `docs/pi-deploy.md` — flag any claim (e.g. "LAN-only, no public
  exposure") that no longer matches reality.
- Where a host setting is checkable from the repo (compose port binding, env vars, image pins), put
  a runnable test in `tests_to_write`; otherwise give explicit `ssh pi-songs` verification commands.

## Per-persona / per-group file priorities

- **Architect:** core domain models, `services/`, `web/app.py` boundaries, `db.py`.
- **Developer:** business logic, `import_service.py`, `extractor.py`, `pptx_reader.py`,
  `normalize.py`, utility functions, tests.
- **Database/Data:** `db.py` (all methods, `init_schema()`), `import_service.py` (transaction
  usage), `web/app.py` (DB lifecycle, `get_db()`, thread-pool usage).
- **DevOps/DevSecOps/Security:** `Dockerfile`, compose files, `.github/workflows/`, `scripts/`,
  cloudflared/Traefik config — **plus the live pi-songs host**.
- **Product Manager:** web templates, CLI help, `README.md`, `GETTING_STARTED.md`, report output
  formats, user-facing error messages.
- **UAT:** `tests/test_e2e_playwright.py`, `tests/test_e2e_htmx.py`, `tests/test_uat_acceptance.py`,
  all templates, `web/app.py` routes, static JS (`upload.js`, `reports.js`).
- **Accessibility:** all HTML templates, CSS/static, DOM/focus-manipulating JS, HTMX partials.
- **QA:** all `tests/`, `conftest.py`, `.github/workflows/ci.yml`, templates, output-format code
  (CSV, XLSX, JSON).

Known sharp edges to look for:
- **Data:** `Database` thread-safety (background import threads + web request threads sharing a
  connection); SQLite **WAL** journal mode + `busy_timeout` appropriate for the concurrent
  read/write pattern; races in `_maybe_commit()`; missing indexes on hot-path WHERE/JOIN/ORDER BY;
  long-running transactions in `purge_old_import_jobs` / `delete_service_data` blocking readers;
  corruption risk on SIGKILL mid-write (non-WAL); NULL-in-UNIQUE pitfalls.
- **Security:** the tunnel forwards public traffic — confirm `/metrics`, `/jobs` aren't reachable
  unauthenticated; CSRF on forms; upload handling (type/size/path-traversal); `TRUSTED_PROXY` set so
  rate limiting works behind the tunnel.
- **UAT (real browser, Playwright only — not TestClient):** upload workflow end-to-end
  (`/upload` → PPTX → progress → `/songs`); each report type (CSV/XLSX/stats) end-to-end; HTMX
  interactions (live search/sort/date filters) without duplicating tables or JS console errors;
  CSRF-protected forms actually submit in a real browser; job status polling
  (pending→running→complete/failed); valid download files with expected headers.
- **Accessibility:** labels (not placeholder-only), ARIA live regions for HTMX swaps, contrast
  ≥4.5:1, working skip-nav, table markup (`<th scope>`/`<caption>`), `aria-sort` on sortable
  headers, focus trap/restore on modals, usable at 200% zoom.

## Commands

```bash
# worktree + env
agent-worktree new song-history code-review
cd ~/projects/.worktrees/highland-song-history/code-review
uv sync --extra dev

# test + lint (part of the review); respect markers — skip e2e unless browser setup is available
uv run pytest -m "not e2e"
uv run pytest -m e2e            # only with Playwright/browser available
uv run ruff check .
```

## Threat model / exposure notes

Public internet via cloudflared tunnel + Traefik. Trust boundary is the tunnel edge — anything bound
to `0.0.0.0` on pi-songs that the tunnel forwards is publicly reachable. Sensitive assets: CF API
token, tunnel token, CSRF secret, upload password (all must be `600` at rest). Per-client rate
limiting depends on `TRUSTED_PROXY`. Upload endpoint accepts user files → validate type/size/path.

## History file

- **Location:** `docs/code-review-history.md`  (ten-persona reviews; prepend `## Review N`)

## PR review (`adversarial-pr-review` skill)

Knobs for the PR-scoped, adversarial proposer→challenger review (`~/.claude/skills/adversarial-pr-review`). Reviews a single PR's diff and posts one consolidated comment; complements the whole-repo `full-code-review` above (reuse its "Project identity & stack", "Per-persona / per-group file priorities", and "Threat model / exposure notes" sections for context — do not re-derive them here).

- **Confidence threshold:** 80.
- **Challengers per finding:** 1 (use `--thorough` for a 3-challenger median on high-stakes PRs — auth/CSRF, upload handling, SQLite concurrency, or anything touching the public tunnel edge).
- **Lenses that apply:** all 5 apply.
  - `bug:` — correctness/logic in extraction, credit resolution, reporting math, HTMX route handlers.
  - `claude-md:` — repo conventions: `uv`, `src/` layout, Ruff 100-char, snake_case, pytest markers, `secret <path>/<field>` over reading `~/.env`.
  - `sec/data:` — public web app behind a cloudflared tunnel: CSRF on forms, upload type/size/path-traversal, `/metrics` & `/jobs` reachability, `TRUSTED_PROXY`; **plus SQLite concurrency** (background import threads + web request threads sharing a connection, WAL/`busy_timeout`, `_maybe_commit()` races, long transactions blocking readers).
  - `history:` — regressions against git-blame context and prior PR-comment decisions (e.g. re-introducing a removed public endpoint, un-pinning a digest-pinned third-party image, reverting a concurrency fix).
  - `test:` — meaningful tests for changed behavior; **respect the pytest markers** (`unit`/`integration`/`slow`/`e2e`) — don't demand `e2e`/Playwright/browser tests unless the change clearly warrants end-to-end coverage (upload workflow, report download, HTMX interactions).
- **Priority paths for diff context** (see the full "Per-persona / per-group file priorities" table above for the complete map):
  - `src/worship_catalog/extractor.py`, `pptx_reader.py`, `normalize.py`, `import_service.py`, `library.py`, `service_slots.py` — core extraction/credit/import logic.
  - `src/worship_catalog/db.py` — schema, connection/thread-safety, transactions.
  - `src/worship_catalog/web/` — routes (`app.py`), templates, static JS (`upload.js`, `reports.js`).
  - `src/worship_catalog/cli.py`, `ocr.py`, `notify.py` — CLI + external integrations.
  - `tests/` and `conftest.py` — matching test coverage for changed behavior.
  - `Dockerfile`, `compose.yml`, `.github/workflows/ci.yml` — deploy/CI surface (public tunnel edge).
- **Post on no findings:** false.
- **Out of scope for challengers (score low):** anything Ruff, mypy, Bandit, pip-audit, gitleaks, or pre-commit already catch (lint/format, type errors, obvious insecure patterns, dependency CVEs, committed secrets); pre-existing issues not touched by this PR; lines the PR did not modify; style nits.
- **What "real, in-scope" looks like here:**
  - A new/changed route handler that shares the `Database` connection across the import thread pool without the WAL/`busy_timeout`/locking that the rest of the code relies on, risking `database is locked` under concurrent import + web load.
  - A new form or upload path that skips CSRF validation or file type/size/path-traversal checks, or an endpoint that becomes reachable unauthenticated through the tunnel (e.g. `/metrics`, `/jobs`).
  - Changed extraction/credit-resolution or reporting logic (e.g. `extractor.py`, `normalize.py`) with no matching `unit`/`integration` test covering the new behavior.
