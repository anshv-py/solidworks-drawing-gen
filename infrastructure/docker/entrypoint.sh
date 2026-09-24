#!/bin/sh
# A host-mounted persistent disk (Render: /data) may arrive root-owned. Started as root, take
# ownership of /data, then drop to the unprivileged user to run the app.
set -e
if [ "$(id -u)" = 0 ]; then
  mkdir -p /data
  chown cadai:cadai /data
  if command -v setpriv >/dev/null 2>&1; then
    exec setpriv --reuid=cadai --regid=cadai --init-groups "$@"
  fi
  echo "entrypoint: setpriv not found, running as root" >&2
fi
exec "$@"
