#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${ROOT_DIR}/.local-runtime"
PROXY_UNIT="${REPORT_PROXY_UNIT:-report-proxy.service}"
PROXY_URL="${REPORT_PROXY_URL:-http://127.0.0.1:11437/v1}"
LOG_FILE="${REPORT_PROXY_LOG_FILE:-${RUNTIME_DIR}/report-proxy.log}"

if systemctl --user --quiet is-active "${PROXY_UNIT}"; then
  MAIN_PID="$(systemctl --user show -p MainPID --value "${PROXY_UNIT}")"
  echo "[local] report proxy running via systemd (${PROXY_UNIT}) with pid ${MAIN_PID}"
else
  echo "[local] report proxy not running"
fi

if curl -fsS "${PROXY_URL}/models" >/dev/null 2>&1; then
  echo "[local] endpoint healthy: ${PROXY_URL}"
else
  echo "[local] endpoint not responding: ${PROXY_URL}"
fi

if [[ -f "${LOG_FILE}" ]]; then
  echo "[local] log: ${LOG_FILE}"
fi
