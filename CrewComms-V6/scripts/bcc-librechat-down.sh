#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${ROOT_DIR}/.bcc-runtime"

stop_service() {
  local name="$1"
  local pid_file="${RUNTIME_DIR}/${name}.pid"

  if [[ ! -f "${pid_file}" ]]; then
    echo "[bcc] ${name} not tracked"
    return
  fi

  local pid
  pid="$(cat "${pid_file}")"
  if kill -0 "${pid}" 2>/dev/null; then
    echo "[bcc] stopping ${name} pid ${pid}"
    kill "${pid}"
  else
    echo "[bcc] ${name} pid ${pid} is not running"
  fi
  rm -f "${pid_file}"
}

stop_service backend
stop_service mongo
