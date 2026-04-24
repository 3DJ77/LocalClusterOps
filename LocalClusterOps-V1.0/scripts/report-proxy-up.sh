#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

RUNTIME_DIR="${ROOT_DIR}/.local-runtime"
mkdir -p "${RUNTIME_DIR}"
PROXY_UNIT="${REPORT_PROXY_UNIT:-report-proxy.service}"
PROXY_URL="${REPORT_PROXY_URL:-http://127.0.0.1:11437/v1}"
LOG_FILE="${REPORT_PROXY_LOG_FILE:-${RUNTIME_DIR}/report-proxy.log}"
PID_FILE="${REPORT_PROXY_PID_FILE:-${RUNTIME_DIR}/report-proxy.pid}"
PROXY_BIN="${REPORT_PROXY_BIN:-${ROOT_DIR}/scripts/report_proxy.py}"

endpoint_ready() {
  curl -fsS "${PROXY_URL}/models" >/dev/null 2>&1
}

if endpoint_ready; then
  echo "[local] report proxy endpoint already healthy: ${PROXY_URL}"
  exit 0
fi

load_state="$(systemctl --user show -p LoadState --value "${PROXY_UNIT}" 2>/dev/null || echo "not-found")"
if [[ "${load_state}" != "not-found" ]]; then
  if systemctl --user --quiet is-active "${PROXY_UNIT}"; then
    echo "[local] report proxy already running via systemd (${PROXY_UNIT})"
  else
    echo "[local] starting report proxy service (${PROXY_UNIT}); log: ${LOG_FILE}"
    systemctl --user daemon-reload
    systemctl --user start "${PROXY_UNIT}"
  fi
else
  if [[ -f "${PID_FILE}" ]] && kill -0 "$(cat "${PID_FILE}")" 2>/dev/null; then
    echo "[local] report proxy already running in direct mode pid $(cat "${PID_FILE}")"
  else
    echo "[local] ${PROXY_UNIT} not found; starting direct proxy process with ${PROXY_BIN}"
    setsid python3 "${PROXY_BIN}" >"${LOG_FILE}" 2>&1 < /dev/null &
    echo "$!" >"${PID_FILE}"
  fi
fi

echo "[local] waiting for report proxy on ${PROXY_URL}"
for _ in {1..40}; do
  if endpoint_ready; then
    echo "[local] report proxy ready: ${PROXY_URL}"
    exit 0
  fi
  sleep 0.5
done

echo "[local] WARN: report proxy did not respond yet. Check ${LOG_FILE}"
exit 1
