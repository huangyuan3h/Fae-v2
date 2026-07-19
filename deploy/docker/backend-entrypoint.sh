#!/bin/sh
# Ensure the named volume mount is writable by the fae user, then drop privileges.
set -eu
mkdir -p /app/.data
chown -R fae:fae /app/.data 2>/dev/null || true
exec runuser -u fae -- "$@"
