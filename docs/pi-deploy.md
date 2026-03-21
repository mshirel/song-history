# Pi Deployment Guide

Deploy song-history on a Raspberry Pi in the church dmarc rack.
Traefik handles HTTPS termination via Let's Encrypt DNS-01 (Cloudflare).
The site is LAN-only — no public internet exposure, no port forwarding required.

---

## Architecture

```
Church LAN
  └── Raspberry Pi (dmarc rack, UPS-backed)
        ├── Traefik :80/:443  → Let's Encrypt via Cloudflare DNS-01
        └── song-history :8000 (internal only)

UniFi DNS: songs.highland-coc.com → Pi LAN IP
Cloudflare DNS: highland-coc.com (used only for DNS-01 TXT record challenge)
```

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
sudo apt-get install -y sqlite3   # needed by backup.sh
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

# Make backup script executable
ssh pi@<PI_IP> "chmod +x /opt/song-history/scripts/backup.sh"
```

**What gets transferred:**

```
/opt/song-history/
├── docker-compose.yml            # Pi-specific stack (Traefik + app)
├── .env.example                  # template — copy to .env and fill in
├── worship-catalog.service       # systemd unit for auto-start on boot
├── traefik/
│   └── traefik.yml               # Traefik static config (Cloudflare DNS-01)
└── scripts/
    └── backup.sh                 # nightly backup script (run via cron)
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
0 2 * * * . /home/songs/.pushover.env && /opt/song-history/scripts/backup.sh /opt/song-history/data/worship.db /opt/song-history/backups-usb
```

`backup.sh` sends a Pushover notification if the backup fails. Success is silent.

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

# Reload systemd, enable and start the service
sudo systemctl daemon-reload
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

# 2. Health endpoint
curl -s http://localhost:8000/health
# Expected: {"status":"ok"}

# 3. Songs page loads with data
curl -sf http://localhost:8000/songs | grep -q "Worship Catalog" && echo "PASS" || echo "FAIL"

# 4. Manual backup test
. /home/songs/.pushover.env && /opt/song-history/scripts/backup.sh \
    /opt/song-history/data/worship.db \
    /opt/song-history/backups-usb
ls /opt/song-history/backups-usb/worship-*.sql.gz | tail -1
# Expected: a .sql.gz file dated today

# 5. HTTPS cert (check after ~30s)
curl -sf https://songs.highland-coc.com/health | grep -q "ok" && echo "PASS" || echo "FAIL"
```

| Check | Expected |
|---|---|
| `docker compose ps` | traefik + watcher + song-history running |
| `GET /health` | `{"status":"ok"}` |
| `/songs` page | loads with song data |
| Backup file | `worship-YYYYMMDD-HHMMSS.sql.gz` present |
| HTTPS cert | no browser cert warning |

---

## 15. Update Procedure

```bash
cd /opt/song-history
docker compose pull && docker compose up -d
```

---

## Data Maintenance

Use the `cleanup` CLI commands to fix bad data. Always back up first.

```bash
# Back up the database
/opt/song-history/scripts/backup.sh /opt/song-history/data/worship.db /opt/song-history/backups-usb

# Find duplicate services (same date+name, different file hash)
docker compose run --rm cli cleanup find-duplicates

# Delete services with bad date from a buggy import
docker compose run --rm cli cleanup delete-service --date 0000-00-00 --yes

# Remove orphaned songs left after service deletion
docker compose run --rm cli cleanup orphaned-songs --dry-run
docker compose run --rm cli cleanup orphaned-songs --yes
```

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
| Backup fails | Run manually and check stderr; verify `sqlite3` is installed |

---

## Graceful Shutdown

The web service shuts down its import thread pool before exiting.
`docker-compose.yml` sets `stop_grace_period: 35s` so Docker waits up to 35 seconds
for in-flight import jobs to finish before sending SIGKILL. This protects SQLite from
partial writes when running `docker compose down` or restarting the service.
