#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

APP_PORT="${LOCAL_CHAT_PORT:-3096}"
MONGO_PORT="${LOCAL_MONGO_PORT:-27017}"

echo "[local] reboot: stopping tracked services"
./scripts/local-chat-down.sh || true

kill_port() {
  local port="$1"
  local label="$2"
  local pids
  pids="$(ss -ltnp "sport = :${port}" 2>/dev/null | awk 'NR>1 {print $NF}' | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u || true)"
  if [[ -z "${pids}" ]]; then
    pids="$(fuser -n tcp "${port}" 2>/dev/null | tr -s ' ' '\n' | grep -E '^[0-9]+$' || true)"
  fi
  if [[ -n "${pids}" ]]; then
    echo "[local] reboot: killing orphan ${label} on :${port} (pids: ${pids})"
    kill ${pids} 2>/dev/null || true
    sleep 0.5
    kill -9 ${pids} 2>/dev/null || true
  fi
}

kill_port "${APP_PORT}" "backend"
kill_port "${MONGO_PORT}" "mongo"

rm -f "${ROOT_DIR}/.local-runtime/backend.pid" "${ROOT_DIR}/.local-runtime/mongo.pid"

echo "[local] reboot: starting stack"
exec ./scripts/local-chat-up.sh
