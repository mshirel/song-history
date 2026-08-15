#!/bin/sh
# deploy/pi/firewall/ufw-setup.sh — host firewall baseline for pi-songs (#447).
#
# pi-songs serves songs.highland-coc.com publicly via an OUTBOUND cloudflared
# tunnel, so the host needs NO inbound ports for the public site. It permits
# SSH and node_exporter on tailscale0; Tailnet grants are the authorization
# boundary after the Pi moves to the church network. Church-LAN policy is
# enforced at the church firewall, not here.
#
# NOTE: ufw only filters HOST-process ports (e.g. node_exporter :9100). Docker
# publishes :8000/:2000 via iptables in a way that BYPASSES ufw's INPUT chain —
# those are restricted separately in docker-user-firewall.sh (DOCKER-USER hook).
#
# Run as root. Idempotent. Re-running re-asserts the ruleset.
set -e

PROM=10.20.100.245   # lxc-obsv-prometheus — the only host allowed to scrape
MGMT=10.20.0.0/16    # homelab management supernet (covers the admin workstation)

ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow from "$MGMT" to any port 22 proto tcp comment 'SSH homelab mgmt'
ufw allow in on tailscale0 to any port 22 proto tcp comment 'SSH Tailnet'
ufw allow 80/tcp  comment 'Traefik HTTP (LAN alias + redirect)'
ufw allow 443/tcp comment 'Traefik HTTPS (LAN alias + Kuma monitor)'
ufw allow from "$PROM" to any port 9100 proto tcp comment 'Prometheus node_exporter'
ufw allow in on tailscale0 to any port 9100 proto tcp comment 'Prometheus node_exporter Tailnet'
ufw --force enable
ufw status verbose
