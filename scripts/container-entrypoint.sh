#!/bin/sh
set -eu

role="${1:-bot}"
shift || true

case "$role" in
  migrate|bot|worker)
    exec python -m anime_qqbot.entrypoints.cli "$role" "$@"
    ;;
  *)
    echo "unknown role: $role" >&2
    exit 64
    ;;
esac
