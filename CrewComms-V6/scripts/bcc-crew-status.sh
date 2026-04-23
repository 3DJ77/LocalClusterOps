#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
MONTY_DIR="${ROOT_DIR}/../Monty"

unit_status() {
  local unit="$1"
  local enabled active
  enabled="$(systemctl --user is-enabled "${unit}" 2>/dev/null || true)"
  active="$(systemctl --user is-active "${unit}" 2>/dev/null || true)"
  printf '[crew] %-20s enabled=%-8s active=%s\n' "${unit}" "${enabled:-unknown}" "${active:-unknown}"
}

unit_status crewcomms.service
unit_status crew-bridge.service
unit_status crew-spike.service
echo "[crew] Deep work runtime: Locutous coding worker, usually codestral:22b"

mike_enabled="$(systemctl --user is-enabled crew-mike.service 2>/dev/null || true)"
mike_active="$(systemctl --user is-active crew-mike.service 2>/dev/null || true)"
printf '[crew] %-20s enabled=%-8s active=%s\n' "crew-mike.service" "${mike_enabled:-unknown}" "${mike_active:-unknown}"
echo "[crew] Remote bounded runtime: external on Prodigy; local crew-mike.service should normally stay disabled"

if curl -fsS http://127.0.0.1:3096/api/config >/dev/null 2>&1; then
  echo "[crew] CrewComms HTTP: ready at http://127.0.0.1:3096"
else
  echo "[crew] CrewComms HTTP: not ready"
fi

if curl -fsS http://127.0.0.1:11436/v1/models >/dev/null 2>&1; then
  echo "[crew] Local-Bridge: ready at http://127.0.0.1:11436/v1"
else
  echo "[crew] Local-Bridge: not ready"
fi

if ssh -o BatchMode=yes -o ConnectTimeout=3 prodigy 'curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags' >/tmp/crew-mike-ollama-tags.json 2>/dev/null; then
  python3 - <<'PY'
from __future__ import annotations

import json
from pathlib import Path

data = json.loads(Path("/tmp/crew-mike-ollama-tags.json").read_text(encoding="utf-8"))
models = [str(item.get("name", "")) for item in data.get("models", []) if item.get("name")]
print(f"[crew] Remote Prodigy Ollama: ready ({len(models)} models)")
if models:
    print("[crew] Remote Prodigy models: " + ", ".join(models[:12]))
PY
else
  echo "[crew] Remote Prodigy Ollama: not checked/reachable over ssh right now"
fi

MONTY_DIR="${MONTY_DIR}" PYTHONPATH="${MONTY_DIR}/src" python3 - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

from monty_comms import poll_packets


def show_lease(label: str, path: Path) -> None:
    if not path.exists():
        print(f"[crew] {label} lease: missing ({path})")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    holder = data.get("holder", "unknown")
    mode = data.get("mode", "unknown")
    expires = data.get("lease_expires_at") or "none"
    reason = data.get("reason", "")
    print(f"[crew] {label} lease: holder={holder} mode={mode} expires={expires} reason={reason}")


monty = Path(os.environ["MONTY_DIR"])
show_lease("Locutous", monty / "state" / "lease_state.json")
show_lease("Remote optional", monty / "state" / "lease_state_prodigy.json")

for label, callsign in (("Deep Work", "Blaster"), ("Remote", "Mike")):
    pending = poll_packets(callsign, limit=5, include_seen=False)
    print(f"[crew] pending for {label}: {pending['pending_count']}")
PY
