#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${ROOT_DIR}/.local-runtime"
APP_HOST="${LOCAL_CHAT_HOST:-127.0.0.1}"
APP_PORT="${LOCAL_CHAT_PORT:-3096}"
APP_URL="http://${APP_HOST}:${APP_PORT}"

status_service() {
  local name="$1"
  local pid_file="${RUNTIME_DIR}/${name}.pid"

  if [[ -f "${pid_file}" ]] && kill -0 "$(cat "${pid_file}")" 2>/dev/null; then
    echo "[local] ${name}: running pid $(cat "${pid_file}")"
  else
    echo "[local] ${name}: stopped"
  fi
}

status_service mongo
status_service backend

if curl -fsS "${APP_URL}/api/config" >/dev/null 2>&1; then
  echo "[local] LibreChat HTTP: ready at ${APP_URL}"
else
  echo "[local] LibreChat HTTP: not ready"
fi

if curl -fsS http://127.0.0.1:11434/v1/models >/dev/null 2>&1; then
  echo "[local] Ollama OpenAI API: ready at http://127.0.0.1:11434/v1"
else
  echo "[local] Ollama OpenAI API: not reachable from this host context"
fi
