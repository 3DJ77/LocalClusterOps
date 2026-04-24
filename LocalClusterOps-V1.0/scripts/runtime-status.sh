#!/usr/bin/env bash
set -euo pipefail

UI_UNIT="${LOCAL_WEB_UNIT:-chat-ui.service}"
BRIDGE_UNIT="${LOCAL_BRIDGE_UNIT:-bridge.service}"
WORKER_UNIT="${LOCAL_TASK_UNIT:-task-worker.service}"
REMOTE_UNIT="${LOCAL_REMOTE_UNIT:-remote-worker.service}"
WEB_UI_URL="${LOCAL_WEB_URL:-http://127.0.0.1:3096}"
TASK_RUNTIME_URL="${LOCAL_TASK_URL:-http://127.0.0.1:11436/v1}"
REMOTE_HOST="${LOCAL_REMOTE_HOST:-remote-host}"
REMOTE_MODELS_URL="${LOCAL_REMOTE_MODELS_URL:-http://127.0.0.1:11434/api/tags}"
REMOTE_MODELS_FILE="$(mktemp)"
trap 'rm -f "${REMOTE_MODELS_FILE}"' EXIT

unit_status() {
  local unit="$1"
  local enabled active
  enabled="$(systemctl --user is-enabled "${unit}" 2>/dev/null || true)"
  active="$(systemctl --user is-active "${unit}" 2>/dev/null || true)"
  printf '[runtime] %-20s enabled=%-8s active=%s\n' "${unit}" "${enabled:-unknown}" "${active:-unknown}"
}

unit_status "${UI_UNIT}"
unit_status "${BRIDGE_UNIT}"
unit_status "${WORKER_UNIT}"
echo "[runtime] Task runtime: local coding and coordination worker"

remote_enabled="$(systemctl --user is-enabled "${REMOTE_UNIT}" 2>/dev/null || true)"
remote_active="$(systemctl --user is-active "${REMOTE_UNIT}" 2>/dev/null || true)"
printf '[runtime] %-20s enabled=%-8s active=%s\n' "${REMOTE_UNIT}" "${remote_enabled:-unknown}" "${remote_active:-unknown}"
echo "[runtime] Remote optional runtime: external host; local helper should normally stay disabled"

if curl -fsS "${WEB_UI_URL}/api/config" >/dev/null 2>&1; then
  echo "[runtime] Web UI: ready at ${WEB_UI_URL}"
else
  echo "[runtime] Web UI: not ready"
fi

if curl -fsS "${TASK_RUNTIME_URL}/models" >/dev/null 2>&1; then
  echo "[runtime] Task Runtime: ready at ${TASK_RUNTIME_URL}"
else
  echo "[runtime] Task Runtime: not ready"
fi

if ssh -o BatchMode=yes -o ConnectTimeout=3 "${REMOTE_HOST}" "curl -fsS --max-time 2 ${REMOTE_MODELS_URL}" >"${REMOTE_MODELS_FILE}" 2>/dev/null; then
  REMOTE_MODELS_FILE="${REMOTE_MODELS_FILE}" python3 - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

data = json.loads(Path(os.environ["REMOTE_MODELS_FILE"]).read_text(encoding="utf-8"))
models = [str(item.get("name", "")) for item in data.get("models", []) if item.get("name")]
print(f"[runtime] Remote optional runtime: ready ({len(models)} models)")
if models:
    print("[runtime] Remote model sample: " + ", ".join(models[:12]))
PY
else
  echo "[runtime] Remote optional runtime: not checked/reachable over ssh right now"
fi
