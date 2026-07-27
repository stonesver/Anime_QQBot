#!/bin/sh
set -eu

role="${1:-worker}"
shift || true

case "$role" in
  migrate|worker)
    exec python -m anime_qqbot.entrypoints.cli "$role" "$@"
    ;;
  *)
    echo "unknown role: $role" >&2
    exit 64
    ;;
esac
