#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bin/release-guard.sh [--allow-dirty] [--expected-dir <name>]

Checks:
  - expected top-level app directory exists
  - legacy/private naming does not appear in tracked paths
  - legacy/private naming does not appear in release-facing files
  - top-level tracked tree shape sanity
  - clean git working tree (unless --allow-dirty)
EOF
}

ALLOW_DIRTY=0
EXPECTED_DIR="${EXPECTED_APP_DIR:-LocalClusterOps-V1.0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --allow-dirty)
      ALLOW_DIRTY=1
      shift
      ;;
    --expected-dir)
      if [[ $# -lt 2 ]]; then
        echo "[guard] ERROR: --expected-dir requires a value" >&2
        exit 2
      fi
      EXPECTED_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[guard] ERROR: unknown argument '$1'" >&2
      usage >&2
      exit 2
      ;;
  esac
done

ROOT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${ROOT_DIR}" ]]; then
  echo "[guard] ERROR: not inside a git repository" >&2
  exit 2
fi
cd "${ROOT_DIR}"

failures=()

add_failure() {
  failures+=("$1")
}

log() {
  echo "[guard] $*"
}

PATH_BANNED_REGEX='CrewComms|crewcomms|(^|/)bcc[^/]*|mizmedia|miz-media'
CONTENT_BANNED_REGEX='CrewComms|crewcomms|crew comms|blue collar crew|mizmedia|miz-media|(^|[^A-Za-z])bcc([^A-Za-z]|$)'

log "Expected app directory: ${EXPECTED_DIR}"

if [[ ! -d "${EXPECTED_DIR}" ]]; then
  add_failure "missing expected top-level directory: ${EXPECTED_DIR}"
fi

if [[ -d "CrewComms-V6" ]]; then
  add_failure "legacy directory still present: CrewComms-V6"
fi

if [[ -n "$(find . -mindepth 1 -maxdepth 1 -type d -name 'LocalClusterOps-V*' -printf '.' 2>/dev/null)" ]]; then
  mapfile -t version_dirs < <(find . -mindepth 1 -maxdepth 1 -type d -name 'LocalClusterOps-V*' -printf '%f\n' | sort)
  if [[ ${#version_dirs[@]} -ne 1 ]]; then
    add_failure "expected exactly one LocalClusterOps-V* directory, found ${#version_dirs[@]}: ${version_dirs[*]}"
  fi
fi

path_hits="$(git ls-files | rg -n -i "${PATH_BANNED_REGEX}" || true)"
if [[ -n "${path_hits}" ]]; then
  add_failure "banned naming found in tracked paths:\n$(echo "${path_hits}" | head -n 20)"
fi

scan_targets=(README.md .gitignore .gitnore bin)
if [[ -d "${EXPECTED_DIR}/scripts" ]]; then
  scan_targets+=("${EXPECTED_DIR}/scripts")
fi
if [[ -f "${EXPECTED_DIR}/librechat.local.yaml" ]]; then
  scan_targets+=("${EXPECTED_DIR}/librechat.local.yaml")
fi

content_hits="$(rg -n -i \
  --glob '!**/node_modules/**' \
  --glob '!**/dist/**' \
  --glob '!**/coverage/**' \
  --glob '!**/package-lock.json' \
  --glob '!**/bun.lock' \
  --glob '!bin/release-guard.sh' \
  "${CONTENT_BANNED_REGEX}" "${scan_targets[@]}" 2>/dev/null || true)"
if [[ -n "${content_hits}" ]]; then
  add_failure "banned naming found in release-facing files:\n$(echo "${content_hits}" | head -n 20)"
fi

top_tree="$(git ls-tree --name-only HEAD | sort)"
log "Top-level tracked entries:"
while IFS= read -r line; do
  [[ -n "${line}" ]] && log "  ${line}"
done <<< "${top_tree}"

if ! echo "${top_tree}" | rg -qx "${EXPECTED_DIR}" >/dev/null 2>&1; then
  add_failure "HEAD tree missing expected top-level entry: ${EXPECTED_DIR}"
fi

if echo "${top_tree}" | rg -qi 'CrewComms|crewcomms' >/dev/null 2>&1; then
  add_failure "HEAD tree still contains CrewComms-named top-level entries"
fi

if [[ ${ALLOW_DIRTY} -eq 0 ]]; then
  status="$(git status --porcelain)"
  if [[ -n "${status}" ]]; then
    add_failure "working tree is not clean (use --allow-dirty to bypass)"
  fi
fi

if [[ ${#failures[@]} -gt 0 ]]; then
  echo
  log "FAILED (${#failures[@]} issue(s))"
  for item in "${failures[@]}"; do
    echo "[guard] - ${item}"
  done
  exit 1
fi

echo
log "PASS: release guard checks completed successfully"
