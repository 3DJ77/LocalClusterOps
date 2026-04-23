#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

APP_HOST="${BCC_LIBRECHAT_HOST:-127.0.0.1}"
APP_PORT="${BCC_LIBRECHAT_PORT:-3096}"
APP_URL="http://${APP_HOST}:${APP_PORT}"
HEALTH_INTERVAL="${BCC_LIBRECHAT_HEALTH_INTERVAL:-30}"

cleanup() {
  local status=$?
  trap - SIGINT SIGTERM EXIT
  echo "[bcc] keepalive: stopping stack"
  ./scripts/bcc-librechat-down.sh || true
  exit "${status}"
}

trap cleanup SIGINT SIGTERM EXIT

echo "[bcc] keepalive: starting stack"
./scripts/bcc-librechat-up.sh

while true; do
  sleep "${HEALTH_INTERVAL}" &
  wait "$!" || true

  if curl -fsS "${APP_URL}/api/config" >/dev/null 2>&1; then
    continue
  fi

  echo "[bcc] keepalive: health check failed for ${APP_URL}; restarting stack"
  ./scripts/bcc-librechat-reboot.sh || true
done
