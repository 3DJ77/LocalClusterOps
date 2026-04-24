#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

RUNTIME_DIR="${ROOT_DIR}/.local-runtime"
mkdir -p "${RUNTIME_DIR}"
PROXY_UNIT="${REPORT_PROXY_UNIT:-report-proxy.service}"
PROXY_URL="${REPORT_PROXY_URL:-http://127.0.0.1:11437/v1}"
LOG_FILE="${REPORT_PROXY_LOG_FILE:-${RUNTIME_DIR}/report-proxy.log}"

if systemctl --user --quiet is-active "${PROXY_UNIT}"; then
  echo "[local] report proxy already running via systemd"
  exit 0
fi

echo "[local] starting report proxy service (${PROXY_UNIT}); log: ${LOG_FILE}"
systemctl --user daemon-reload
systemctl --user start "${PROXY_UNIT}"

echo "[local] waiting for report proxy on ${PROXY_URL}"
for _ in {1..40}; do
  if curl -fsS "${PROXY_URL}/models" >/dev/null 2>&1; then
    echo "[local] report proxy ready: ${PROXY_URL}"
    exit 0
  fi
  sleep 0.5
done

echo "[local] WARN: report proxy did not respond yet. Check ${LOG_FILE}"
exit 1
