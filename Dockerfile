FROM python:3.12-slim

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

RUN chmod +x scripts/import-new.sh

# Install the package with web extras
RUN pip install --no-cache-dir -e ".[web]"

# Runtime volumes:
#   /data     — worship.db (database)
#   /inbox    — new PPTX files to import
#   /config   — reporting.yml (optional override)
VOLUME ["/data", "/inbox"]

ENV DB_PATH=/data/worship.db
ENV INBOX_DIR=/inbox

ENTRYPOINT ["worship-catalog"]
CMD ["--help"]
