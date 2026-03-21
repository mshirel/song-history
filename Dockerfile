# Pin base image to exact digest to prevent supply-chain drift (#26)
# python:3.14-slim — Dependabot bumped from 3.12; CVE scan passing at this digest
FROM python:3.14-slim@sha256:6a27522252aef8432841f224d9baaa6e9fce07b07584154fa0b9a96603af7456

WORKDIR /app

# Build-time version and date, baked into files the app reads at runtime (#261, #262)
ARG APP_VERSION=dev
ARG BUILD_DATE=development

# Upgrade all Debian packages to pull in any security patches issued since
# the base image was published, then install runtime deps.
# This ensures Trivy finds no fixable CVEs even when the base digest is stale.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends \
        libxml2 \
        libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip to latest to clear pip CVEs (CVE-2026-1703, CVE-2025-8869 fixed in pip>=26.0)
RUN pip install --no-cache-dir --upgrade pip

# Copy package files first (for layer caching)
COPY pyproject.toml README.md ./
COPY requirements.lock ./
COPY src/ ./src/
COPY config/ ./config/
COPY scripts/ ./scripts/
# Bundled credit index (#47)
COPY data/library_index.json /app/data/library_index.json

RUN chmod +x scripts/import-new.sh

# Install pinned dependencies from lockfile for reproducible builds (#174),
# then install the package itself (editable not needed in prod).
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps ".[web]"

# Bake version and build date so the About page shows real values (#261, #262)
RUN echo "${APP_VERSION}" > /app/.version \
    && echo "${BUILD_DATE}" > /app/.build-date

# Create a non-root user and group for runtime (#26)
# Fixed UID/GID so host volume permissions can be set to match:
#   sudo chown -R 1001:1001 ./data ./inbox
RUN groupadd --gid 1001 appgroup \
    && useradd --uid 1001 --gid 1001 --no-create-home --shell /sbin/nologin appuser

# Pre-create volume mount points with correct ownership so the non-root
# user can write to them even before the host volume is mounted.
RUN mkdir -p /data /inbox \
    && chown appuser:appgroup /data /inbox

# Runtime volumes:
#   /data     — worship.db (database)
#   /inbox    — new PPTX files to import
#   /config   — reporting.yml (optional override)
VOLUME ["/data", "/inbox"]

ENV DB_PATH=/data/worship.db
ENV INBOX_DIR=/inbox

# Drop privileges before running anything
USER appuser

ENTRYPOINT ["uvicorn"]
CMD ["worship_catalog.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
