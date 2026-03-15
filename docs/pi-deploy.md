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
# Log out and back in for group change to take effect
```

---

## 2. Copy Deployment Files

```bash
sudo mkdir -p /opt/song-history/traefik
sudo chown $USER /opt/song-history

# From your dev machine:
scp -r deploy/pi/* pi@<PI_IP>:/opt/song-history/
```

Or clone the repo and copy:

```bash
git clone https://github.com/mshirel/song-history /tmp/song-history
cp -r /tmp/song-history/deploy/pi/* /opt/song-history/
```

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
mkdir -p /opt/song-history/data /opt/song-history/inbox
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

## 9. Update Procedure

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

The backup service from `compose.yml` (dev stack) is not included here — use a cron job instead:

```bash
# Add to crontab (crontab -e):
0 2 * * * /opt/song-history/scripts/backup.sh /opt/song-history/data/worship.db /opt/song-history/backups
```

Mount `/opt/song-history/backups` to a separate USB drive or network share for offsite protection.
