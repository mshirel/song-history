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
