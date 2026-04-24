#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${ROOT_DIR}/.local-runtime"

stop_service() {
  local name="$1"
  local pid_file="${RUNTIME_DIR}/${name}.pid"

  if [[ ! -f "${pid_file}" ]]; then
    echo "[local] ${name} not tracked"
    return
  fi

  local pid
  pid="$(cat "${pid_file}" 2>/dev/null || true)"
  if [[ -z "${pid}" ]]; then
    echo "[local] ${name} pid file was empty; clearing tracker"
    rm -f "${pid_file}"
    return
  fi

  if kill -0 "${pid}" 2>/dev/null; then
    echo "[local] stopping ${name} pid ${pid}"
    kill "${pid}"
    for _ in {1..20}; do
      if ! kill -0 "${pid}" 2>/dev/null; then
        break
      fi
      sleep 0.1
    done
    if kill -0 "${pid}" 2>/dev/null; then
      echo "[local] force stopping ${name} pid ${pid}"
      kill -9 "${pid}" 2>/dev/null || true
    fi
  else
    echo "[local] ${name} pid ${pid} is not running"
  fi
  rm -f "${pid_file}"
}

stop_service backend
stop_service mongo
