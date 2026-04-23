#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

RUNTIME_DIR="${ROOT_DIR}/.bcc-runtime"
mkdir -p "${RUNTIME_DIR}"

APP_HOST="${BCC_LIBRECHAT_HOST:-127.0.0.1}"
APP_PORT="${BCC_LIBRECHAT_PORT:-3096}"
MONGO_PORT="${BCC_MONGO_PORT:-27017}"
APP_URL="http://${APP_HOST}:${APP_PORT}"
MONGO_URI="mongodb://127.0.0.1:${MONGO_PORT}/LibreChat"

start_service() {
  local name="$1"
  shift
  local pid_file="${RUNTIME_DIR}/${name}.pid"
  local log_file="${RUNTIME_DIR}/${name}.log"

  if [[ -f "${pid_file}" ]] && kill -0 "$(cat "${pid_file}")" 2>/dev/null; then
    echo "[bcc] ${name} already running with pid $(cat "${pid_file}")"
    return
  fi

  echo "[bcc] starting ${name}; log: ${log_file}"
  setsid "$@" >"${log_file}" 2>&1 < /dev/null &
  echo "$!" >"${pid_file}"
}

if [[ -f "librechat.bcc.yaml" ]]; then
  cp librechat.bcc.yaml librechat.yaml
  echo "[bcc] Activated librechat.bcc.yaml -> librechat.yaml"
fi

"${ROOT_DIR}/scripts/bcc-mizmedia-up.sh"

start_service mongo env BCC_MONGO_PORT="${MONGO_PORT}" node scripts/bcc-mongo-memory.js

echo "[bcc] waiting for MongoDB on 127.0.0.1:${MONGO_PORT}"
for _ in {1..40}; do
  if node -e "const net=require('net'); const s=net.connect(Number(process.env.BCC_MONGO_PORT),'127.0.0.1'); s.once('connect',()=>{s.end(); process.exit(0)}); s.once('error',()=>process.exit(1)); setTimeout(()=>process.exit(1),500);" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

start_service backend env \
  NODE_ENV=production \
  HOST="${APP_HOST}" \
  PORT="${APP_PORT}" \
  DOMAIN_CLIENT="${APP_URL}" \
  DOMAIN_SERVER="${APP_URL}" \
  MONGO_URI="${MONGO_URI}" \
  node api/server/index.js

echo "[bcc] waiting for LibreChat on ${APP_URL}"
for _ in {1..40}; do
  if curl -fsS "${APP_URL}/api/config" >/dev/null 2>&1; then
    echo "[bcc] LibreChat ready: ${APP_URL}"
    exit 0
  fi
  sleep 0.5
done

echo "[bcc] WARN: LibreChat did not respond yet. Check ${RUNTIME_DIR}/backend.log"
exit 1
