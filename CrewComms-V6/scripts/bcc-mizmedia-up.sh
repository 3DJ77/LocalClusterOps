#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

RUNTIME_DIR="${ROOT_DIR}/.bcc-runtime"
mkdir -p "${RUNTIME_DIR}"
LOG_FILE="${RUNTIME_DIR}/mizmedia-proxy.log"

if systemctl --user --quiet is-active mizmedia-proxy.service; then
  echo "[bcc] mizmedia-proxy already running via systemd"
  exit 0
fi

echo "[bcc] starting mizmedia-proxy service; log: ${LOG_FILE}"
systemctl --user daemon-reload
systemctl --user start mizmedia-proxy.service

echo "[bcc] waiting for mizmedia-proxy on 127.0.0.1:11437"
for _ in {1..40}; do
  if curl -fsS "http://127.0.0.1:11437/v1/models" >/dev/null 2>&1; then
    echo "[bcc] mizmedia-proxy ready: http://127.0.0.1:11437/v1"
    exit 0
  fi
  sleep 0.5
done

echo "[bcc] WARN: mizmedia-proxy did not respond yet. Check ${LOG_FILE}"
exit 1
