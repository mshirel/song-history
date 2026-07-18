#!/bin/sh
# Allow non-root Promtail (gid 0) to enumerate Docker's log directories.

set -eu

CONTAINERS_DIR=${1:-/var/lib/docker/containers}

if [ ! -d "$CONTAINERS_DIR" ]; then
    echo "Docker containers directory not found: $CONTAINERS_DIR" >&2
    exit 1
fi

# Docker creates each container directory as 0710 root:root.  The execute bit
# lets gid 0 open a path it already knows, but Promtail's wildcard discovery
# also needs the read bit to enumerate both this directory and its children.
chmod g+rx "$CONTAINERS_DIR"
find "$CONTAINERS_DIR" -mindepth 1 -maxdepth 1 -type d -exec chmod g+rx {} +
