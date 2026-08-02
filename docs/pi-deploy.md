# Pi Deployment Guide

Deploy song-history on a Raspberry Pi (pi-songs, `10.20.249.10`, DMZ VLAN 249).

> **PUBLIC EXPOSURE.** `https://songs.highland-coc.com` is reachable from the
> **public internet** via a Cloudflare Tunnel (cloudflared). It is NOT LAN-only.
> Browsing/report data (songs, services, leaders, preachers, sermon titles) is
> intentionally public (see #455); only the write/admin surface (`/upload`,
> `/jobs`) is gated by `UPLOAD_PASSWORD`. Treat the host as internet-adjacent and
> keep it hardened (firewall, key-only SSH, 600 secrets) — see **Security
> Hardening** below before exposing or re-deploying.

---

## Architecture

```
Public internet ──HTTPS──> Cloudflare edge ──tunnel(outbound)──> cloudflared ─┐
                                                                              │ (internal docker net)
Church LAN ──HTTPS──> Traefik :80/:443 ──────────────────────────────────────┤
                                                                              ▼
                                                              song-history :8000 (FastAPI)

Raspberry Pi (pi-songs, DMZ VLAN 249, UPS-backed):
  ├── cloudflared        → outbound tunnel to Cloudflare edge (no inbound ports)
  ├── traefik :80/:443   → LAN alias (pi-songs.tanx95.us) + Let's Encrypt DNS-01
  ├── song-history :8000 → app; host port firewalled to the Prometheus scraper
  ├── watcher            → import loop (same image; heartbeat healthcheck, #514)
  └── promtail           → ships container logs to homelab Loki (non-root, #514)

UniFi DNS: pi-songs.tanx95.us → 10.20.249.10 (LAN alias)
Cloudflare: songs.highland-coc.com → tunnel; highland-coc.com zone for DNS-01
```

---

## Security Hardening (required for the public host)

Because the host serves a public tunnel, lock it down. Codified in the repo:
`deploy/pi/firewall/`, `deploy/pi/ssh/00-hardening.conf`, and `init.sh`.

- **Secrets (`.env`) must be `600`** — it holds the Cloudflare API + tunnel
  tokens, CSRF secret, and upload password. `init.sh` refuses a non-600 `.env`
  (#446). `sudo chmod 600 /opt/song-history/.env`.
- **Host firewall (ufw)** — deny inbound by default; allow only SSH from the
  homelab mgmt supernet, 80/443 (Traefik LAN alias + Kuma), and the Prometheus
  scraper (`10.20.100.245`) to `:9100`. Run `deploy/pi/firewall/ufw-setup.sh`
  (#447). The public site needs **no** inbound ports (tunnel is outbound).
- **Docker-published `:8000`/`:2000`** bypass ufw's INPUT chain, so they are
  restricted to the Prometheus scraper via the `DOCKER-USER` chain —
  `deploy/pi/firewall/docker-user-firewall.sh` + its systemd unit (#447).
- **Key-only SSH** — install `deploy/pi/ssh/00-hardening.conf` (the `00-` prefix
  must sort before `50-cloud-init.conf`); `PasswordAuthentication no` (#452).
- **fail2ban for SSH** — install `fail2ban`, copy
  `deploy/pi/fail2ban/jail.d/sshd.local` into `/etc/fail2ban/jail.d/`, then
  `sudo systemctl enable --now fail2ban`. Verify with
  `systemctl is-active fail2ban` and `sudo fail2ban-client status sshd` (#452).
  On Ubuntu Noble / Python 3.12, the distro `fail2ban` package also needs the
  `asynchat` compatibility module; install `pyasynchat` into
  `/usr/local/lib/python3.12/dist-packages/asynchat` before starting the
  service if the journal shows `No module named 'asynchat'`.
- **Token rotation** — if `.env` was ever world-readable, rotate the Cloudflare
  API token and tunnel token in the Cloudflare dashboard (#446).
- **promtail runs non-root** (`user: "10001:0"`, #514) — least privilege on the
  public host. It reads container logs as gid 0 (root group) instead of root.
  The host needs two prep steps:
  1. Docker json logs are `0640 root:root`, but their container directories are
     `0710`: gid 0 can open a known file but cannot enumerate Promtail's wildcard.
     Install and enable `promtail-log-access.path`; it runs the least-privilege
     `prepare-promtail-log-access.sh` helper whenever Docker creates a container
     directory, adding only group read/traverse to the directory tree. The helper
     also removes legacy default ACLs from this tree: those ACLs make Docker's
     resolver files unreadable to non-root containers and break outbound DNS.
  2. Promtail writes `positions.yaml` into the mounted positions dir, so make it
     writable by the uid/gid: `sudo chown -R 10001:0 /opt/song-history/promtail
     && sudo chmod -R g+rwX /opt/song-history/promtail`.
  If promtail logs `permission denied` on the log path or positions file, one of
  these steps was missed.
- **App image is digest-pinned** (`ghcr.io/mshirel/song-history:sha-…@sha256:…`,
  #512) — `docker compose pull` no longer swaps app code from mutable `:latest`.
  Bump it via a reviewed Dependabot PR (#502) or by re-pinning the `sha-<commit>`
  tag + digest CI publishes; `song-history` and `watcher` must stay in lockstep.

---

## Hardware Prerequisites

- Raspberry Pi 4 or 5, 4 GB+ RAM
- MicroSD card (32 GB+) or USB SSD
- UPS (recommended — protects SQLite from corruption on power loss)

---

## 1. OS Setup

Install **Raspberry Pi OS Lite 64-bit** (no desktop). Enable SSH during flash with Raspberry Pi Imager.

```bash
# After first boot — update and install Docker
sudo apt-get update && sudo apt-get upgrade -y
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
sudo apt-get install -y sqlite3 fail2ban   # backup + SSH hardening
# Log out and back in for docker group change to take effect
```

---

## 2. Transfer Deployment Files

**No repo clone needed on the Pi.** The app runs entirely from the Docker image pulled from GHCR.
Only a handful of config files are needed on the host.

**From your dev machine** (run from the repo root):

```bash
# Create the deployment directory on the Pi
ssh pi@<PI_IP> "sudo mkdir -p /opt/song-history/traefik && sudo chown \$USER /opt/song-history"

# Copy the deployment config — this is everything the Pi needs
rsync -av deploy/pi/ pi@<PI_IP>:/opt/song-history/

# Make host scripts executable
ssh pi@<PI_IP> "chmod +x /opt/song-history/scripts/*.sh"
```

**What gets transferred:**

```
/opt/song-history/
├── docker-compose.yml            # Pi-specific stack (Traefik + app)
├── .env.example                  # template — copy to .env and fill in
├── worship-catalog.service       # systemd unit for auto-start on boot
├── systemd/
│   ├── promtail-log-access.path  # notices newly-created container directories
│   └── promtail-log-access.service # restores non-root directory enumeration
├── traefik/
│   └── traefik.yml               # Traefik static config (Cloudflare DNS-01)
└── scripts/
    ├── backup.sh                 # nightly backup script (run via cron)
    └── prepare-promtail-log-access.sh # grants directory-only log discovery
```

That's it. No source code, no tests, no docs on the Pi.

---

## 3. Create the .env File

```bash
ssh pi@<PI_IP>
cd /opt/song-history
cp .env.example .env
nano .env   # fill in real values
```

**Never commit `.env` to git. It contains secrets.**

Required values:

| Variable | Value |
|---|---|
| `CLOUDFLARE_API_TOKEN` | API token with `highland-coc.com` Zone:DNS:Edit |
| `CSRF_SECRET` | Stable random string — generate with `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `ANTHROPIC_API_KEY` | Only needed for `--ocr`; leave blank to disable |
| `PUSHOVER_APP_TOKEN` | Optional: Pushover app token for backup failure alerts |
| `PUSHOVER_USER_KEY` | Optional: Pushover user key — required alongside `PUSHOVER_APP_TOKEN` |

---

## 4. Cloudflare API Token

1. Go to [Cloudflare API Tokens](https://dash.cloudflare.com/profile/api-tokens)
2. Create Token → Use template **Edit zone DNS**
3. Zone Resources: Include → Specific zone → `highland-coc.com`
4. Copy the token into `.env`

---

## 5. Prepare acme.json

Traefik requires this file to exist with `600` permissions before first start:

```bash
touch /opt/song-history/traefik/acme.json
chmod 600 /opt/song-history/traefik/acme.json
```

---

## 6. Create Data Directories

```bash
mkdir -p /opt/song-history/data \
         /opt/song-history/inbox \
         /opt/song-history/inbox/archive \
         /opt/song-history/inbox/quarantine \
         /opt/song-history/backups
```

---

## 7. Seed the Database

Copy your dev `worship.db` to the Pi using the seed script. Run from your **dev machine**:

```bash
./scripts/seed-pi-db.sh pi@<PI_IP> data/worship.db
```

The script will:
1. Run `PRAGMA integrity_check` and `PRAGMA foreign_key_check` on the source DB
2. Show the service count and date range — confirm this is the right DB
3. Prompt for confirmation before copying
4. Copy via `scp` to `/opt/song-history/data/worship.db`
5. Verify the copy with `PRAGMA integrity_check` on the Pi

**After seeding, the Pi DB is authoritative. Do not overwrite it with an older dev copy.**

---

## 8. USB Thumbdrive Backup Setup

A USB thumbdrive is the simplest offsite backup. Plug one in and:

```bash
# Find the device
lsblk

# Format if needed (only on first use)
sudo mkfs.ext4 /dev/sda1

# Create mount point
sudo mkdir -p /opt/song-history/backups-usb

# Get the UUID for fstab
sudo blkid /dev/sda1
```

Add to `/etc/fstab` for auto-mount on boot:

```
UUID=<your-uuid>  /opt/song-history/backups-usb  ext4  defaults,nofail  0  2
```

```bash
sudo mount -a
sudo chown $USER /opt/song-history/backups-usb
```

---

## 9. Configure Backup Cron

Backups run via a host cron job — no sidecar container needed.

### Create the Pushover env file

Store the Pushover credentials in a dedicated file so cron can source them
(cron jobs run with a minimal environment and do not inherit shell exports):

```bash
cat > /home/songs/.pushover.env << 'EOF'
export PUSHOVER_APP_TOKEN=<your-app-token>
export PUSHOVER_USER_KEY=<your-user-key>
EOF
chmod 600 /home/songs/.pushover.env
```

### Add the cron entry

```bash
crontab -e
```

Add:
```
# Nightly backup at 2 AM — sources Pushover keys, writes to USB drive
# Output logged to ~/backup.log because cron silently discards output when no MTA is installed.
0 2 * * * . /home/songs/.pushover.env && /opt/song-history/scripts/backup.sh /opt/song-history/data/worship.db /opt/song-history/backups-usb >> /home/songs/backup.log 2>&1
```

`backup.sh` sends a Pushover notification if the backup fails. Success is silent.

> **Important:** Without the `>> ~/backup.log 2>&1` redirect, cron silently
> discards all output when no MTA (mail server) is installed — which is the
> default on Raspberry Pi OS Lite. If the backup fails, you get no error
> message and no Pushover alert (because the error may occur before the
> script's trap handler runs). Always redirect to a log file.

---

## 10. UniFi DNS Override

In UniFi Network → Settings → Networks → DNS:
- Add a local DNS record: `songs.highland-coc.com` → `<Pi LAN IP>`

---

## 11. Dedicated Service User

Create a `songs` system user to own the stack. This avoids running containers as your
personal login account and makes systemd management cleaner.

```bash
# Create system user with a home directory and docker access
sudo useradd --system --create-home --shell /bin/bash songs
sudo usermod -aG docker songs

# Hand ownership of the deployment directory to songs
sudo chown -R songs:songs /opt/song-history
```

> **Note:** The `docker` group grants effective root on the host. Real privilege
> separation comes from the non-root `appuser` inside the container. The `songs`
> user is a housekeeping measure, not a security boundary.

---

## 12. Systemd Auto-Start

Install the provided `worship-catalog.service` unit so the stack starts
automatically on boot — critical for a headless Pi in a utility closet.

```bash
# Copy the unit file
sudo cp /opt/song-history/worship-catalog.service /etc/systemd/system/
sudo cp /opt/song-history/systemd/promtail-log-access.* /etc/systemd/system/

# Prepare existing Docker directories and keep future ones discoverable
sudo /opt/song-history/scripts/prepare-promtail-log-access.sh
sudo chown -R 10001:0 /opt/song-history/promtail
sudo chmod -R g+rwX /opt/song-history/promtail

# Reload systemd, enable and start the service
sudo systemctl daemon-reload
sudo systemctl enable --now promtail-log-access.path
sudo systemctl enable --now worship-catalog
```

Useful commands:

```bash
sudo systemctl status worship-catalog   # check health
sudo journalctl -u worship-catalog -f   # follow logs
sudo systemctl restart worship-catalog  # restart after config change
```

---

## 13. Start the Stack

If you prefer to start manually (or for first-time testing before enabling systemd):

```bash
cd /opt/song-history
docker compose up -d
docker compose logs -f   # watch for Traefik to obtain cert (~30 s)
```

Once the Let's Encrypt cert is issued, `https://songs.highland-coc.com` will be live on the church LAN.

---

## 14. Go/No-Go Verification Checklist

```bash
# 1. All containers running
docker compose ps
# Expected: traefik, watcher, and song-history all running/healthy

# 2. Health endpoint (via Traefik — port 8000 is internal to Docker)
curl -sf http://localhost/health
# Expected: {"status":"ok"}

# 3. Songs page loads with data
curl -sf http://localhost/songs | grep -q "Worship Catalog" && echo "PASS" || echo "FAIL"

# 4. Manual backup test
. /home/songs/.pushover.env && /opt/song-history/scripts/backup.sh \
    /opt/song-history/data/worship.db \
    /opt/song-history/backups-usb
ls /opt/song-history/backups-usb/worship-*.sql.gz | tail -1
# Expected: a .sql.gz file dated today

# 5. HTTPS cert (check after ~30s)
curl -sf https://songs.highland-coc.com/health | grep -q "ok" && echo "PASS" || echo "FAIL"

# 6. Backup log writable
touch /home/songs/backup.log && echo "PASS" || echo "FAIL"

# 7. Promtail is configured and running as the dedicated non-root uid
compose_user="$(docker compose config --format json | jq -r '.services.promtail.user')"
promtail_id="$(docker compose ps -q promtail)"
runtime_user="$(docker inspect --format '{{.Config.User}}' "$promtail_id")"
test "$compose_user" = "10001:0" && test "$runtime_user" = "10001:0" \
    && echo "PASS" || echo "FAIL"

# 8. Promtail can persist positions for its newly-created Docker log file
promtail_log="$(docker inspect --format '{{.LogPath}}' "$promtail_id")"
sudo grep -Fq "$promtail_log" /opt/song-history/promtail/positions.yaml \
    && echo "PASS" || echo "FAIL"

# 9. A known application log line reaches Loki and advances positions
positions_before="$(stat -c %Y /opt/song-history/promtail/positions.yaml)"
marker="promtail-verify-$(date +%s)"
curl -sS -o /dev/null "http://localhost/$marker"  # expected HTTP 404
sleep 10
positions_after="$(stat -c %Y /opt/song-history/promtail/positions.yaml)"
loki_hits="$(curl -fsSG 'http://10.20.100.249:3100/loki/api/v1/query_range' \
    --data-urlencode 'query={host="pi-songs"} |= "'"$marker"'"' \
    --data-urlencode "start=$(date -d '2 minutes ago' +%s%N)" \
    --data-urlencode "end=$(date +%s%N)" \
    --data-urlencode 'limit=10' | jq '[.data.result[].values[]] | length')"
test "$positions_after" -gt "$positions_before" && test "$loki_hits" -ge 1 \
    && echo "PASS" || echo "FAIL"
```

| Check | Expected |
|---|---|
| `docker compose ps` | traefik + watcher + song-history running |
| `GET /health` (via localhost:80) | `{"status":"ok"}` |
| `/songs` page | loads with song data |
| Backup file | `worship-YYYYMMDD-HHMMSS.sql.gz` present |
| HTTPS cert | no browser cert warning |
| Backup log | `~/backup.log` writable |
| Promtail user | Compose and container runtime both report `10001:0` |
| Promtail positions | new container log path appears in `positions.yaml` |
| Loki delivery | unique 404 request line appears in Loki and positions advance |

---

## 15. Update Procedure

Run as the **`songs`** user — `.env` is `600` and owned by `songs`, so other
admins (e.g. `matt`) can't read it for `docker compose` and will get
`open .env: permission denied`:

```bash
sudo -u songs bash -c 'cd /opt/song-history && docker compose pull && docker compose up -d'
```

> **Note:** recreating the `song-history` container causes a **few-second window**
> where Traefik returns `404` for the public host until it re-discovers the new
> container — expected; it clears within seconds. Verify after with
> `curl -sf https://songs.highland-coc.com/health`.

If the compose file itself changed in the repo, copy it over first (the Pi's
copy is a manual, drifted copy — `compose pull` does **not** apply compose-file
changes): reconcile by hand, backing up the existing file.

---

## Data Maintenance

Use the `cleanup` CLI commands to fix bad data. Always back up first.

```bash
# Back up the database
/opt/song-history/scripts/backup.sh /opt/song-history/data/worship.db /opt/song-history/backups-usb

# Find duplicate services (same date+name, different file hash)
docker compose run --rm song-history worship-catalog cleanup find-duplicates --db /data/worship.db

# Delete services with bad date from a buggy import
docker compose run --rm song-history worship-catalog cleanup delete-service --date 0000-00-00 --db /data/worship.db --yes

# Remove orphaned songs left after service deletion
docker compose run --rm song-history worship-catalog cleanup orphaned-songs --db /data/worship.db --dry-run
docker compose run --rm song-history worship-catalog cleanup orphaned-songs --db /data/worship.db --yes
```

> **Note:** The `--db /data/worship.db` flag is required because the CLI
> defaults to `data/worship.db` (a relative path that doesn't exist inside
> the container). The Docker volume mounts the DB at `/data/worship.db`.

See [docs/data-cleanup.md](data-cleanup.md) for the full command reference and re-import workflow.

---

## Troubleshooting

| Symptom | Check |
|---|---|
| Cert not issued | `docker compose logs traefik` — look for ACME errors |
| `acme.json` errors | Verify `chmod 600 traefik/acme.json` |
| App not reachable | `docker compose ps` — all services healthy? |
| Wrong DNS | `nslookup songs.highland-coc.com` from LAN — should return Pi IP |
| DB permission error | `sudo chown -R 1001:1001 /opt/song-history/data` (matches app UID) |
| Backup fails silently | Check `~/backup.log`; run manually with `. ~/.pushover.env && /opt/song-history/scripts/backup.sh ...` and watch stderr |
| No Pushover on failure | Verify `~/backup.log` redirect is in crontab; check `~/.pushover.env` has valid tokens |
| `curl localhost:8000` fails | Port 8000 is internal to Docker — use `curl localhost/health` (via Traefik on port 80) |

---

## Graceful Shutdown

The web service shuts down its import thread pool before exiting.
`docker-compose.yml` sets `stop_grace_period: 35s` so Docker waits up to 35 seconds
for in-flight import jobs to finish before sending SIGKILL. This protects SQLite from
partial writes when running `docker compose down` or restarting the service.
