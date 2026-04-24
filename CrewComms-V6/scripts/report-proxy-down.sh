#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PROXY_UNIT="${REPORT_PROXY_UNIT:-report-proxy.service}"
RUNTIME_DIR="${ROOT_DIR}/.local-runtime"
PID_FILE="${REPORT_PROXY_PID_FILE:-${RUNTIME_DIR}/report-proxy.pid}"

stopped_any=0

load_state="$(systemctl --user show -p LoadState --value "${PROXY_UNIT}" 2>/dev/null || echo "not-found")"
if [[ "${load_state}" != "not-found" ]] && systemctl --user --quiet is-active "${PROXY_UNIT}"; then
  PID="$(systemctl --user show -p MainPID --value "${PROXY_UNIT}")"
  systemctl --user stop "${PROXY_UNIT}"
  echo "[local] stopped report proxy (${PROXY_UNIT}) pid ${PID}"
  stopped_any=1
fi

if [[ -f "${PID_FILE}" ]]; then
  PID="$(cat "${PID_FILE}")"
  if kill -0 "${PID}" 2>/dev/null; then
    kill "${PID}"
    echo "[local] stopped report proxy direct process pid ${PID}"
    stopped_any=1
  fi
  rm -f "${PID_FILE}"
fi

if [[ "${stopped_any}" -eq 0 ]]; then
  echo "[local] report proxy not running"
fi
