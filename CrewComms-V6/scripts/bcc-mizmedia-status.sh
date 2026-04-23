#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${ROOT_DIR}/.bcc-runtime"
LOG_FILE="${RUNTIME_DIR}/mizmedia-proxy.log"

if systemctl --user --quiet is-active mizmedia-proxy.service; then
  MAIN_PID="$(systemctl --user show -p MainPID --value mizmedia-proxy.service)"
  echo "[bcc] mizmedia-proxy running via systemd with pid ${MAIN_PID}"
else
  echo "[bcc] mizmedia-proxy not running"
fi

if curl -fsS "http://127.0.0.1:11437/v1/models" >/dev/null 2>&1; then
  echo "[bcc] endpoint healthy: http://127.0.0.1:11437/v1"
else
  echo "[bcc] endpoint not responding: http://127.0.0.1:11437/v1"
fi

if [[ -f "${LOG_FILE}" ]]; then
  echo "[bcc] log: ${LOG_FILE}"
fi
