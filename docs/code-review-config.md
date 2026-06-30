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
