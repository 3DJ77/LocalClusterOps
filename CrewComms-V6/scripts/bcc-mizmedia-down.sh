#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

if ! systemctl --user --quiet is-active mizmedia-proxy.service; then
  echo "[bcc] mizmedia-proxy not running"
  exit 0
fi

PID="$(systemctl --user show -p MainPID --value mizmedia-proxy.service)"
systemctl --user stop mizmedia-proxy.service
echo "[bcc] stopped mizmedia-proxy pid ${PID}"
