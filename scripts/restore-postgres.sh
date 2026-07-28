#!/bin/sh
set -eu

usage() {
  printf 'usage: %s BACKUP.sql.gz [--yes]\n' "$0" >&2
  exit 64
}

backup="${1:-}"
confirm="${2:-}"
[ -n "$backup" ] || usage
[ -f "$backup" ] || { printf 'backup not found: %s\n' "$backup" >&2; exit 66; }
[ -z "$confirm" ] || [ "$confirm" = "--yes" ] || usage
gzip -t "$backup"

if [ "$confirm" != "--yes" ]; then
  printf 'This replaces the anime database. Type "restore anime" to continue: ' >&2
  IFS= read -r answer
  [ "$answer" = "restore anime" ] || { printf 'restore cancelled\n' >&2; exit 1; }
fi

raw="$(mktemp "${TMPDIR:-/tmp}/anime-restore.XXXXXX.sql")"
trap 'rm -f "$raw"' EXIT HUP INT TERM
gzip -dc "$backup" > "$raw"

docker compose stop worker astrbot napcat
docker compose up -d --wait postgres
docker compose exec -T postgres psql \
  --username anime \
  --dbname anime \
  --set ON_ERROR_STOP=1 \
  --command 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'
docker compose exec -T postgres psql \
  --username anime \
  --dbname anime \
  --set ON_ERROR_STOP=1 < "$raw"
docker compose run --rm --no-deps migrate
docker compose run --rm --no-deps --entrypoint /bin/sh migrate \
  -c 'alembic current | grep -q "0011_complete_mikan_pipeline (head)"'

if [ "${RESTORE_SKIP_APP_START:-0}" != "1" ]; then
  docker compose up -d --no-build --no-deps --wait worker astrbot napcat
fi

printf 'restore completed and migration head verified: %s\n' "$backup"
