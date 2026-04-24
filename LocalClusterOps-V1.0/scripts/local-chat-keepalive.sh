#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

APP_HOST="${LOCAL_CHAT_HOST:-127.0.0.1}"
APP_PORT="${LOCAL_CHAT_PORT:-3096}"
APP_URL="http://${APP_HOST}:${APP_PORT}"
HEALTH_INTERVAL="${LOCAL_CHAT_HEALTH_INTERVAL:-30}"

cleanup() {
  local status=$?
  trap - SIGINT SIGTERM EXIT
  echo "[local] keepalive: stopping stack"
  ./scripts/local-chat-down.sh || true
  exit "${status}"
}

trap cleanup SIGINT SIGTERM EXIT

echo "[local] keepalive: starting stack"
./scripts/local-chat-up.sh

while true; do
  sleep "${HEALTH_INTERVAL}" &
  wait "$!" || true

  if curl -fsS "${APP_URL}/api/config" >/dev/null 2>&1; then
    continue
  fi

  echo "[local] keepalive: health check failed for ${APP_URL}; restarting stack"
  ./scripts/local-chat-reboot.sh || true
done
