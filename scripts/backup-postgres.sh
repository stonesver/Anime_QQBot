#!/bin/sh
set -eu

umask 077
backup_dir="${BACKUP_DIR:-./backups}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="${backup_dir}/anime-${timestamp}.sql.gz"
raw="${target}.tmp.sql"
compressed="${target}.tmp"

mkdir -p "$backup_dir"
trap 'rm -f "$raw" "$compressed"' EXIT HUP INT TERM

docker compose exec -T postgres pg_dump \
  --username anime \
  --dbname anime \
  --no-owner \
  --no-acl > "$raw"
gzip -9 -c "$raw" > "$compressed"
gzip -t "$compressed"
mv "$compressed" "$target"

printf '%s\n' "$target"
