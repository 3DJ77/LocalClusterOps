#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

echo "[bcc] Root: ${ROOT_DIR}"

if [[ ! -f ".env" ]]; then
  cp .env.example .env
  echo "[bcc] Created .env from .env.example"
fi

if [[ -f "librechat.bcc.yaml" ]]; then
  cp librechat.bcc.yaml librechat.yaml
  echo "[bcc] Activated librechat.bcc.yaml -> librechat.yaml"
fi

if [[ ! -d "node_modules" ]]; then
  echo "[bcc] Installing dependencies..."
  npm ci
fi

if [[ ! -f "packages/data-schemas/dist/index.cjs" ]]; then
  echo "[bcc] Building workspace packages..."
  npm run build:packages
fi

echo "[bcc] Checking Ollama tags endpoint..."
if curl -s http://127.0.0.1:11434/api/tags >/dev/null; then
  echo "[bcc] Ollama is reachable at http://127.0.0.1:11434"
else
  echo "[bcc] WARN: Ollama is not reachable at http://127.0.0.1:11434"
fi

cat <<'EOF'
[bcc] Bootstrap complete.

Start services in separate terminals:
  npm run backend
  npm run frontend:dev

Known infra dependencies:
  - MongoDB (required for full backend operation)
  - Meilisearch/related search components (optional but logs errors if absent)
EOF
