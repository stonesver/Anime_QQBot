#!/bin/sh
set -eu

project_dir="$(CDPATH= cd "$(dirname "$0")/.." && pwd -P)"
cd "$project_dir"

skip_backup=0
skip_build=0
for arg in "$@"; do
  case "$arg" in
    --no-backup) skip_backup=1 ;;
    --no-build) skip_build=1 ;;
    *)
      printf 'usage: %s [--no-backup] [--no-build]\n' "$0" >&2
      exit 64
      ;;
  esac
done

log() { printf '[deploy-v02] %s\n' "$*"; }
fail() { printf '[deploy-v02] ERROR: %s\n' "$*" >&2; exit 1; }

read_env() {
  awk -F= -v key="$1" '
    $0 !~ /^[[:space:]]*#/ && $1 == key {
      value = substr($0, index($0, "=") + 1)
      sub(/\r$/, "", value)
      print value
      exit
    }
  ' .env
}

validate_configuration() {
  [ -f compose.yaml ] || fail "compose.yaml not found"
  [ -f Dockerfile.astrbot ] || fail "Dockerfile.astrbot not found"
  [ -f .env ] || fail ".env not found"
  password="$(read_env POSTGRES_PASSWORD)"
  token="$(read_env ONEBOT_TOKEN)"
  [ -n "$password" ] || fail "POSTGRES_PASSWORD is missing from .env"
  [ -n "$token" ] || fail "ONEBOT_TOKEN is missing from .env"
  case "$password" in replace-*|change-me*) fail "POSTGRES_PASSWORD is still a placeholder" ;; esac
  case "$token" in replace-*|change-me*) fail "ONEBOT_TOKEN is still a placeholder" ;; esac
  [ "${#token}" -ge 24 ] || fail "ONEBOT_TOKEN must contain at least 24 characters"
  case "$token" in
    *[!A-Za-z0-9._~-]*) fail "ONEBOT_TOKEN may only contain URL-safe characters" ;;
  esac
  grep -qFx 'FROM soulter/astrbot:v4.26.7' Dockerfile.astrbot ||
    fail "AstrBot image is not pinned to v4.26.7"
  grep -q 'image: mlikiowa/napcat-docker:v4.18.13' compose.yaml ||
    fail "NapCat image is not pinned to v4.18.13"
  if grep -Eq '(^|[[:space:]])[^#]*:latest([[:space:]]|$)' compose.yaml Dockerfile.astrbot; then
    fail "latest image tags are forbidden"
  fi
  docker compose config --quiet || fail "compose config invalid"
}

tag_running_image() {
  service="$1"
  rollback_ref="$2"
  container="$(docker compose ps -q "$service" 2>/dev/null || true)"
  [ -n "$container" ] || return 0
  image_id="$(docker inspect --format '{{.Image}}' "$container")"
  [ -n "$image_id" ] || fail "cannot inspect current $service image"
  docker image tag "$image_id" "$rollback_ref"
}

rollback_images() {
  log "attempting application image rollback"
  rolled_back=0
  if docker image inspect anime-qqbot:rollback >/dev/null 2>&1; then
    docker image tag anime-qqbot:rollback anime-qqbot:"$app_tag"
    rolled_back=1
  fi
  if docker image inspect anime-astrbot:rollback >/dev/null 2>&1; then
    docker image tag anime-astrbot:rollback anime-astrbot:"$app_tag"
    rolled_back=1
  fi
  if [ "$rolled_back" = "1" ]; then
    docker compose up -d --no-build --no-deps --force-recreate worker astrbot
  fi
}

validate_configuration
app_tag="$(read_env IMAGE_TAG)"
app_tag="${app_tag:-0.2.0}"

lock_dir="$project_dir/.deploy-multisource.lock"
mkdir "$lock_dir" 2>/dev/null || fail "another deployment is already running"
trap 'rmdir "$lock_dir" 2>/dev/null || true' EXIT HUP INT TERM

if [ "$skip_backup" = "0" ] && [ -n "$(docker compose ps -q postgres 2>/dev/null || true)" ]; then
  log "creating PostgreSQL backup"
  scripts/backup-postgres.sh || fail "backup failed"
fi

tag_running_image worker anime-qqbot:rollback
tag_running_image astrbot anime-astrbot:rollback

if [ "$skip_build" = "0" ]; then
  log "building application images before replacing services"
  docker compose build --pull worker astrbot migrate || fail "image build failed"
fi
log "pulling fixed third-party images"
docker compose pull postgres napcat || fail "image pull failed"

log "starting PostgreSQL"
docker compose up -d --wait postgres || fail "PostgreSQL did not become healthy"

log "running migrations to completion"
docker compose run --rm --no-deps migrate || fail "migration failed"

log "updating worker and AstrBot"
if ! docker compose up -d --no-build --no-deps --wait worker astrbot; then
  rollback_images
  fail "worker or AstrBot failed; application images were rolled back when available"
fi

log "updating NapCat"
if ! docker compose up -d --no-build --no-deps --wait napcat; then
  rollback_images
  fail "NapCat failed; application images were rolled back when available"
fi

docker compose ps
log "deployment completed"
log "NapCat WebUI: http://127.0.0.1:${NAPCAT_WEBUI_PORT:-6099}"
log "AstrBot WebUI: http://127.0.0.1:${ASTRBOT_WEBUI_PORT:-6185}"
