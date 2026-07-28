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

umask 077
printf '%s\n' \
  '{ "network": { "httpServers": [], "httpSseServers": [], "httpClients": [], "websocketServers": [], "websocketClients": [ { "enable": true, "name": "astrbot", "url": "ws://astrbot:6199/ws", "reportSelfMessage": false, "messagePostFormat": "array", "token": "'"${token}"'", "debug": false, "heartInterval": 30000, "reconnectInterval": 30000 } ], "plugins": [] }, "musicSignUrl": "", "enableLocalFile2Url": false, "parseMultMsg": false }' \
  > /app/templates/astrbot.json

unset ONEBOT_TOKEN
export MODE=astrbot
exec bash /app/entrypoint.sh
