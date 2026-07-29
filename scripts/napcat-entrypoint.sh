#!/bin/bash
set -euo pipefail

token="${ONEBOT_TOKEN:-}"
if [ "${#token}" -lt 24 ]; then
  printf 'ONEBOT_TOKEN must contain at least 24 characters\n' >&2
  exit 64
fi
case "$token" in
  *[!A-Za-z0-9._~-]*)
    printf 'ONEBOT_TOKEN may only contain URL-safe characters\n' >&2
    exit 64
    ;;
esac

template_path="${NAPCAT_TEMPLATE_PATH:-/app/templates/astrbot.json}"
config_dir="${NAPCAT_CONFIG_DIR:-/app/napcat/config}"
upstream_entrypoint="${NAPCAT_UPSTREAM_ENTRYPOINT:-/app/entrypoint.sh}"

write_onebot_config() {
  target="$1"
  printf '%s\n' \
    '{ "network": { "httpServers": [ { "enable": true, "name": "astrbot-status", "host": "0.0.0.0", "port": 3000, "enableCors": false, "enableWebsocket": false, "messagePostFormat": "array", "token": "'"${token}"'", "debug": false } ], "httpSseServers": [], "httpClients": [], "websocketServers": [], "websocketClients": [ { "enable": true, "name": "astrbot", "url": "ws://astrbot:6199/ws", "reportSelfMessage": false, "messagePostFormat": "array", "token": "'"${token}"'", "debug": false, "heartInterval": 30000, "reconnectInterval": 30000 } ], "plugins": [] }, "musicSignUrl": "", "enableLocalFile2Url": false, "parseMultMsg": false }' \
    > "$target"
}

umask 077
write_onebot_config "$template_path"
for account_config in "$config_dir"/onebot11_*.json; do
  [ -f "$account_config" ] || continue
  write_onebot_config "$account_config"
done

unset ONEBOT_TOKEN
export MODE=astrbot
exec bash "$upstream_entrypoint"
