#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PROXY_UNIT="${REPORT_PROXY_UNIT:-report-proxy.service}"

if ! systemctl --user --quiet is-active "${PROXY_UNIT}"; then
  echo "[local] report proxy not running"
  exit 0
fi

PID="$(systemctl --user show -p MainPID --value "${PROXY_UNIT}")"
systemctl --user stop "${PROXY_UNIT}"
echo "[local] stopped report proxy (${PROXY_UNIT}) pid ${PID}"
