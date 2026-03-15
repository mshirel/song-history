.PHONY: help test lint typecheck security build scan up down logs backup-verify

REPO   = ghcr.io/mshirel/song-history
SHA    = $(shell git rev-parse --short HEAD)
IMAGE  = $(REPO):sha-$(SHA)

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

test:  ## Run test suite with coverage
	python3 -m pytest

lint:  ## Ruff linter
	python3 -m ruff check src/

typecheck:  ## Mypy strict type check
	python3 -m mypy src/

security:  ## bandit + pip-audit
	python3 -m bandit -r src/ -ll -c pyproject.toml
	python3 -m pip_audit --skip-editable

build:  ## Build Docker image tagged :sha-<HEAD>
	docker build -t $(IMAGE) .

scan: build  ## Trivy CVE scan on locally built image
	trivy image --severity CRITICAL,HIGH --ignore-unfixed $(IMAGE)

up:  ## Start all services (detached)
	docker compose up -d

down:  ## Stop all services
	docker compose down

logs:  ## Tail logs from all services
	docker compose logs -f

backup-verify:  ## Verify most recent backup file integrity
	@latest=$$(ls -t backups/worship-*.sql.gz 2>/dev/null | head -1); \
	if [ -z "$$latest" ]; then echo "No backups found in ./backups/"; exit 1; fi; \
	echo "Verifying $$latest ..."; \
	gzip -t "$$latest" && echo "OK: $$latest is valid"
