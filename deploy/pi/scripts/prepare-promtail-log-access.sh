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

# Older setup guidance applied a default ACL to this tree.  Docker's generated
# hosts/hostname/resolv.conf files inherited other=--- from that ACL, leaving
# non-root containers unable to resolve DNS.  Remove only the default ACL from
# the container root and immediate container directories; their access ACLs
# and the group permissions Promtail needs remain intact.
python3 - "$CONTAINERS_DIR" <<'PY'
import errno
import os
import sys
from pathlib import Path

root = Path(sys.argv[1])
directories = [root, *(path for path in root.iterdir() if path.is_dir())]
for directory in directories:
    try:
        os.removexattr(directory, "system.posix_acl_default")
    except OSError as exc:
        if exc.errno not in {errno.ENODATA, errno.ENOTSUP}:
            raise
PY

# Repair containers already created under the stale ACL.  These three files
# are Docker-managed network metadata, not application secrets, and must be
# readable by the configured non-root container user.
find "$CONTAINERS_DIR" -mindepth 2 -maxdepth 2 -type f \
    \( -name hosts -o -name hostname -o -name resolv.conf \) \
    -exec chmod o+r {} +
