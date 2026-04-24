#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

echo "[local] Root: ${ROOT_DIR}"

if [[ ! -f ".env" ]]; then
  cp .env.example .env
  echo "[local] Created .env from .env.example"
fi

if [[ -f "librechat.local.yaml" ]]; then
  cp librechat.local.yaml librechat.yaml
  echo "[local] Activated librechat.local.yaml -> librechat.yaml"
fi

if [[ ! -d "node_modules" ]]; then
  echo "[local] Installing dependencies..."
  npm ci
fi

if [[ ! -f "packages/data-schemas/dist/index.cjs" ]]; then
  echo "[local] Building workspace packages..."
  npm run build:packages
fi

echo "[local] Checking Ollama tags endpoint..."
if curl -s http://127.0.0.1:11434/api/tags >/dev/null; then
  echo "[local] Ollama is reachable at http://127.0.0.1:11434"
else
  echo "[local] WARN: Ollama is not reachable at http://127.0.0.1:11434"
fi

cat <<'EOF'
[local] Bootstrap complete.

Start services in separate terminals:
  npm run backend
  npm run frontend:dev

Known infra dependencies:
  - MongoDB (required for full backend operation)
  - Meilisearch/related search components (optional but logs errors if absent)
EOF
