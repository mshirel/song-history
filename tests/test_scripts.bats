#!/usr/bin/env bats
# tests/test_scripts.bats — shell-level tests for scripts and deployment config
# Run with: bats tests/test_scripts.bats

# ---------------------------------------------------------------------------
# Pi / Docker Compose deployment config (#48)
# ---------------------------------------------------------------------------

@test "deploy/pi/docker-compose.yml exists" {
  [ -f "deploy/pi/docker-compose.yml" ]
}

@test "deploy/pi/.env.example exists" {
  [ -f "deploy/pi/.env.example" ]
}

@test ".env.example contains CLOUDFLARE_API_TOKEN placeholder" {
  grep -q "CLOUDFLARE_API_TOKEN" deploy/pi/.env.example
}

@test ".env.example contains ANTHROPIC_API_KEY placeholder" {
  grep -q "ANTHROPIC_API_KEY" deploy/pi/.env.example
}

@test "docker-compose.yml references traefik service" {
  grep -q "traefik" deploy/pi/docker-compose.yml
}

@test "docker-compose.yml references song-history service" {
  grep -q "song-history" deploy/pi/docker-compose.yml
}

@test "docker-compose.yml does not contain hardcoded secrets" {
  run grep -E "sk-ant-|CF_API_TOKEN=[^\$\{]" deploy/pi/docker-compose.yml
  [ "$status" -ne 0 ]
}

@test "traefik static config exists" {
  [ -f "deploy/pi/traefik/traefik.yml" ]
}

@test "traefik config references cloudflare DNS challenge provider" {
  grep -qi "cloudflare" deploy/pi/traefik/traefik.yml
}

@test "docker-compose.yml references highland-coc.com domain" {
  grep -q "highland-coc.com" deploy/pi/docker-compose.yml
}

@test "docker-compose.yml declares /data volume mount" {
  grep -q "/data" deploy/pi/docker-compose.yml
}

@test "docs/pi-deploy.md exists" {
  [ -f "docs/pi-deploy.md" ]
}

@test "pi-deploy.md documents chmod 600 for acme.json" {
  grep -q "chmod 600" docs/pi-deploy.md
}

@test "pi-deploy.md documents the update procedure" {
  grep -q "docker compose pull" docs/pi-deploy.md
}

# ---------------------------------------------------------------------------
# Root compose.yml for local development (#67)
# ---------------------------------------------------------------------------

@test "root compose.yml exists" {
  [ -f "compose.yml" ]
}

@test "root compose.yml is valid YAML (python parse)" {
  run python3 -c "import yaml; yaml.safe_load(open('compose.yml')); print('ok')"
  [ "$status" -eq 0 ]
}

@test "root compose.yml defines web service" {
  grep -q "^  web:" compose.yml
}

@test "root compose.yml mounts ./data volume" {
  grep -q "./data" compose.yml
}

@test "root compose.yml publishes port 8000" {
  grep -q "8000" compose.yml
}

# ---------------------------------------------------------------------------
# Pi init.sh acme.json validation (#65)
# ---------------------------------------------------------------------------

@test "deploy/pi/init.sh exists" {
  [ -f "deploy/pi/init.sh" ]
}

@test "deploy/pi/init.sh is executable" {
  [ -x "deploy/pi/init.sh" ]
}

@test "deploy/pi/init.sh contains acme.json permission check" {
  grep -q "acme.json" deploy/pi/init.sh
  grep -q "600" deploy/pi/init.sh
}

# ---------------------------------------------------------------------------
# Pi backup sidecar (#64)
# ---------------------------------------------------------------------------

@test "deploy/pi/docker-compose.yml defines backup service" {
  grep -q "^  backup:" deploy/pi/docker-compose.yml
}

@test "deploy/pi/backups/.gitkeep exists to track backup directory" {
  [ -f "deploy/pi/backups/.gitkeep" ]
}

# ---------------------------------------------------------------------------
# import-new.sh SIGTERM handling (#103)
# ---------------------------------------------------------------------------

@test "import-new.sh contains SIGTERM trap" {
  grep -q "SIGTERM" scripts/import-new.sh
}

@test "import-new.sh trap handler calls exit" {
  grep -A2 "_shutdown" scripts/import-new.sh | grep -q "exit"
}

# ---------------------------------------------------------------------------
# backup.sh EXIT trap for temp file cleanup (#63)
# ---------------------------------------------------------------------------

@test "backup.sh contains EXIT trap" {
  grep -q "EXIT" scripts/backup.sh
  grep -q "trap" scripts/backup.sh
}
