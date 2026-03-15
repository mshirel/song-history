# Pin base image to exact digest to prevent supply-chain drift (#26)
FROM python:3.12-slim@sha256:ccc7089399c8bb65dd1fb3ed6d55efa538a3f5e7fca3f5988ac3b5b87e593bf0

WORKDIR /app

# Install system dependencies (for python-pptx / lxml)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 \
    libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Copy package files first (for layer caching)
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY config/ ./config/
COPY scripts/ ./scripts/
# Bundled credit index (#47)
COPY data/library_index.json /app/data/library_index.json

RUN chmod +x scripts/import-new.sh

# Install the package with web extras
RUN pip install --no-cache-dir -e ".[web]"

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

ENTRYPOINT ["worship-catalog"]
CMD ["--help"]
