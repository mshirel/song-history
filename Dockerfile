# Pin base image to exact digest to prevent supply-chain drift (#26)
# python:3.12-slim — GA release matching CI (3.12) and the pyproject target (#403).
# Reverted from a Dependabot bump to 3.14 (pre-release). Dependabot must be
# restricted to GA Python minors so it cannot re-introduce a pre-release runtime.
FROM python:3.12-slim@sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203

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
# then install the package itself (--no-deps: deps already in lockfile) (#294).
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps .

# Remove pip from the runtime image (#595).  pip bundles its own dependencies
# under pip/_vendor — currently msgpack 1.1.2 (GHSA-6v7p-g79w-8964) and
# setuptools 70.3.0 (CVE-2025-47273, CVE-2026-59890).  They are invisible to
# `pip list` because vendored code is not an installed distribution, but they
# are real files in the image and Trivy flags them, blocking every push.
#
# `pip install --upgrade pip` above means the vendored set changes with
# whatever pip is newest at build time, so pinning would only defer this.
# Nothing needs pip at runtime — every dependency is installed above, and the
# HEALTHCHECK uses urllib from the stdlib — so drop it entirely.  This also
# removes the ability to install packages into a running container.
RUN python -m pip uninstall --yes pip \
    && rm -rf /usr/local/lib/python3.12/site-packages/pip \
              /usr/local/lib/python3.12/site-packages/pip-*.dist-info \
              /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.12 \
    && ! command -v pip

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

# Liveness probe baked into the image so standalone `docker run` (and any
# orchestrator that doesn't use the compose healthcheck) can detect a dead
# uvicorn process (#402). Mirrors the compose healthcheck.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

ENTRYPOINT ["uvicorn"]
CMD ["worship_catalog.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
