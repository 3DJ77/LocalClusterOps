#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="$SCRIPT_DIR/../.venv-kiwix-mcp/bin/python"
MCP_SCRIPT="$SCRIPT_DIR/mcp_kiwix.py"

if [ ! -x "$VENV_PY" ]; then
    echo "Missing Kiwix MCP venv python: $VENV_PY" >&2
    exit 1
fi

exec "$VENV_PY" "$MCP_SCRIPT"
