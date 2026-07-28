#!/bin/sh
set -eu

role="${1:-astrbot}"
if [ "$#" -gt 0 ]; then
  shift
fi

case "$role" in
  astrbot)
    plugin_source="${ANIME_PLUGIN_SOURCE:-/opt/anime-qqbot/astrbot_plugin_anime_tracking}"
    astrbot_data="${ASTRBOT_DATA_DIR:-/AstrBot/data}"
    astrbot_main="${ASTRBOT_MAIN:-/AstrBot/main.py}"
    plugin_parent="$astrbot_data/plugins"
    plugin_target="$plugin_parent/astrbot_plugin_anime_tracking"
    plugin_staging="$plugin_parent/.astrbot_plugin_anime_tracking.image.$$"
    plugin_previous="$plugin_parent/.astrbot_plugin_anime_tracking.previous.$$"

    [ -d "$plugin_source" ] || {
      echo "bundled AstrBot plugin not found: $plugin_source" >&2
      exit 66
    }
    mkdir -p "$plugin_parent"
    rm -rf "$plugin_staging" "$plugin_previous"
    cp -R "$plugin_source" "$plugin_staging"

    restore_plugin() {
      rm -rf "$plugin_staging"
      if [ -d "$plugin_previous" ] && [ ! -e "$plugin_target" ]; then
        mv "$plugin_previous" "$plugin_target"
      fi
    }
    trap restore_plugin EXIT HUP INT TERM

    if [ -e "$plugin_target" ]; then
      mv "$plugin_target" "$plugin_previous"
    fi
    mv "$plugin_staging" "$plugin_target"
    rm -rf "$plugin_previous"
    trap - EXIT HUP INT TERM
    exec python "$astrbot_main" "$@"
    ;;
  migrate|worker|map-mikan|map-anilist)
    cd "${ANIME_APP_DIR:-/opt/anime-qqbot}"
    exec python -m anime_qqbot.entrypoints.cli "$role" "$@"
    ;;
  *)
    echo "unknown role: $role" >&2
    exit 64
    ;;
esac
