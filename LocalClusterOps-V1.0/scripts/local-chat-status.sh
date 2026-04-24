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
  local pid=""

  if [[ -f "${pid_file}" ]]; then
    pid="$(cat "${pid_file}" 2>/dev/null || true)"
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      echo "[local] ${name}: running pid ${pid}"
      return
    fi
  fi

  echo "[local] ${name}: stopped"
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
