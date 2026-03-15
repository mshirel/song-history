# Pi Deployment Guide

Deploy song-history on a Raspberry Pi in the church dmarc rack.
Traefik handles HTTPS termination via Let's Encrypt DNS-01 (Cloudflare).
The site is LAN-only — no public internet exposure, no port forwarding required.

> **Note on compose.yml location:** The `compose.yml` file is in the root of the
> repository (not under `deploy/pi/`).  When you clone the repo on the Pi, run
> `docker compose` from `/opt/song-history` where the file lives.

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
# Log out and back in for group change to take effect
```

---

## 2. Copy Deployment Files

```bash
sudo mkdir -p /opt/song-history/traefik
sudo chown $USER /opt/song-history

# Clone the repo directly onto the Pi (recommended):
git clone https://github.com/mshirel/song-history /opt/song-history
```

The `compose.yml` at the root of the repo is the deployment file — use it directly from `/opt/song-history`.

---

## 3. Create the .env File

```bash
cd /opt/song-history
cp .env.example .env
nano .env   # fill in real values
```

**Never commit `.env` to git. It contains secrets.**

Required values:

| Variable | Value |
|---|---|
| `CLOUDFLARE_API_TOKEN` | API token with `highland-coc.com` Zone:DNS:Edit |
| `ANTHROPIC_API_KEY` | Only needed for `--ocr`; leave blank to disable |
| `BACKUP_HEALTHCHECK_URL` | Optional: ping URL (healthchecks.io etc.) for backup alerting — see [Backup Alerting](#backup-alerting) |

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

## 6. Create Data Directories and Seed the Database

```bash
mkdir -p /opt/song-history/data /opt/song-history/inbox /opt/song-history/backups
```

### 6a. Seed the Database (Option C — copy dev DB)

The Pi is treated as authoritative from first boot.  Copy your dev `worship.db`
to the Pi using the seed script:

```bash
# From your dev machine — run from the repo root:
./scripts/seed-pi-db.sh pi@<PI_IP> data/worship.db
```

The script will:
1. Run `PRAGMA integrity_check` and `PRAGMA foreign_key_check` on the source DB
2. Show the service count and date range so you can confirm the right DB is being copied
3. Prompt for confirmation before copying
4. Copy via `scp` to `/opt/song-history/data/worship.db`
5. Verify the copy with `PRAGMA integrity_check` on the Pi

If the integrity check fails, the script exits 1 — fix the DB first.

**After seeding, the Pi DB is authoritative.  Do not overwrite it with an older dev copy.**

### 6b. USB Thumbdrive Backup Setup

For offsite protection, mount a USB drive for backups:

```bash
# Find the USB device
lsblk

# Format if needed (only once)
sudo mkfs.ext4 /dev/sda1

# Create mount point
sudo mkdir -p /opt/song-history/backups-usb

# Get the UUID
sudo blkid /dev/sda1
```

Add to `/etc/fstab` for auto-mount on boot (replace UUID with the one from blkid):

```
UUID=<your-uuid>  /opt/song-history/backups-usb  ext4  defaults,nofail  0  2
```

Mount now:

```bash
sudo mount -a
sudo chown $USER /opt/song-history/backups-usb
```

Update the backup cron to write to the USB mount:

```bash
# crontab -e
0 2 * * * BACKUP_HEALTHCHECK_URL=https://hc-ping.com/<your-uuid> \
    /opt/song-history/scripts/backup.sh \
    /opt/song-history/data/worship.db \
    /opt/song-history/backups-usb
```

If you prefer the compose backup service, update the `backup` volume in `compose.yml`:

```yaml
    volumes:
      - ./data:/data:ro
      - /opt/song-history/backups-usb:/backup   # ← point at USB mount
      - ./scripts:/scripts:ro
```

---

## 7. UniFi DNS Override

In UniFi Network → Settings → Networks → DNS:
- Add a local DNS record: `songs.highland-coc.com` → `<Pi LAN IP>`

This ensures the domain resolves to the Pi on the church LAN without leaving the building.

---

## 8. Start the Stack

```bash
cd /opt/song-history
docker compose up -d
docker compose logs -f   # watch for Traefik to obtain cert (~30 s)
```

Once the Let's Encrypt cert is issued, `https://songs.highland-coc.com` will be live on the church LAN.

---

## 9. Go/No-Go Verification Checklist

Run these checks after first deployment.  All must pass before declaring the Pi live.

```bash
# 1. Health endpoint returns {"status":"ok"}
curl -s http://localhost:8000/health
# Expected: {"status":"ok"}

# 2. All containers healthy
docker compose ps
# Expected: web, backup (and watcher if enabled) all show "healthy" or "running"

# 3. Songs page loads
curl -sf http://localhost:8000/songs | grep -q "Worship Catalog" && echo "PASS" || echo "FAIL"

# 4. DB has data (should match what you seeded)
docker compose run --rm cli report stats --all-songs 2>/dev/null | head -5

# 5. Backup runs without error
docker compose exec backup /scripts/backup.sh /data/worship.db /backup
ls /opt/song-history/backups-usb/worship-*.sql.gz | tail -1

# 6. HTTPS works (after cert issues)
curl -sf https://songs.highland-coc.com/health | grep -q "ok" && echo "PASS" || echo "FAIL"
```

| Check | Expected |
|---|---|
| `GET /health` | `{"status":"ok"}` |
| `docker compose ps` | all services healthy |
| `/songs` page | loads with song data |
| Backup file created | `worship-YYYYMMDD-HHMMSS.sql.gz` present |
| HTTPS cert | no browser cert warning |

---

## 10. Update Procedure

```bash
cd /opt/song-history
docker compose pull && docker compose up -d
```

Watchtower (if enabled) does this automatically at 3 AM nightly.

---

## Troubleshooting

| Symptom | Check |
|---|---|
| Cert not issued | `docker compose logs traefik` — look for ACME errors |
| `acme.json` errors | Verify `chmod 600 traefik/acme.json` |
| App not reachable | `docker compose ps` — all services healthy? |
| Wrong DNS | `nslookup songs.highland-coc.com` from LAN — should return Pi IP |
| DB permission error | `sudo chown -R 1001:1001 /opt/song-history/data` (matches app UID) |

---

## Backup

The backup service in `compose.yml` runs nightly and writes compressed SQL dumps to `./backups/`.

**Alternative: cron job** (simpler for Pi without compose backup service):

```bash
# Add to crontab (crontab -e):
0 2 * * * BACKUP_HEALTHCHECK_URL=https://hc-ping.com/<your-uuid> \
    /opt/song-history/scripts/backup.sh \
    /opt/song-history/data/worship.db \
    /opt/song-history/backups-usb
```

Mount `/opt/song-history/backups-usb` to a USB thumbdrive — see [USB Thumbdrive Backup Setup](#6b-usb-thumbdrive-backup-setup).

---

## Backup Alerting

Set `BACKUP_HEALTHCHECK_URL` in `.env` (or in the cron job) to receive alerts when backups stop arriving:

1. Create a free check at [healthchecks.io](https://healthchecks.io) — set period to 25h
2. Copy the ping URL (e.g. `https://hc-ping.com/your-uuid-here`)
3. Add to `.env`:
   ```
   BACKUP_HEALTHCHECK_URL=https://hc-ping.com/your-uuid-here
   ```
4. If a backup doesn't ping within 25 hours, healthchecks.io emails you an alert

The `backup.sh` script automatically skips the ping when `BACKUP_HEALTHCHECK_URL` is not set.

---

## Graceful Shutdown

The web service shuts down its import thread pool with `wait=True` before the process exits.
`compose.yml` sets `stop_grace_period: 35s` for the web service so Docker waits up to 35 seconds
for in-flight import jobs to finish before sending SIGKILL.  This protects SQLite from partial
writes when running `docker compose down` or restarting the service.
