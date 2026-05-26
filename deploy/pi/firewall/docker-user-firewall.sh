#!/bin/sh
# Restrict Docker-published ports 8000/2000 on eth0 to the Prometheus scraper (#447).
# Docker bypasses ufw's INPUT chain, so DOCKER-USER is the supported firewall hook.
set -e
IF=eth0
SRC=10.20.100.245
for port in 8000 2000; do
  iptables -D DOCKER-USER -i "$IF" -p tcp --dport "$port" -s "$SRC" -j RETURN 2>/dev/null || true
  iptables -D DOCKER-USER -i "$IF" -p tcp --dport "$port" -j DROP 2>/dev/null || true
  iptables -I DOCKER-USER -i "$IF" -p tcp --dport "$port" -j DROP
  iptables -I DOCKER-USER -i "$IF" -p tcp --dport "$port" -s "$SRC" -j RETURN
done
