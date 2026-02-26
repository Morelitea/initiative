#!/usr/bin/env bash
# Regenerate frontend API types from the backend OpenAPI spec.
#
# This script does NOT require a running backend. It:
#   1. Activates the backend venv and exports the OpenAPI spec
#   2. Runs Orval to generate TypeScript types and React Query hooks
#   3. Runs Prettier on the generated files to fix formatting
#
# Usage:
#   ./scripts/regen-api.sh
set -euo pipefail

# Ensure nvm-managed Node is on PATH (needed when run from VS Code tasks)
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
FRONTEND_DIR="${ROOT_DIR}/frontend"
SPEC_PATH="${FRONTEND_DIR}/openapi.json"

# ── Step 1: Export OpenAPI spec ──────────────────────────────────────────────

echo "Exporting OpenAPI spec from backend..."

if [[ -f "${BACKEND_DIR}/.venv/bin/python" ]]; then
  PYTHON="${BACKEND_DIR}/.venv/bin/python"
elif [[ -f "${BACKEND_DIR}/.venv/Scripts/python.exe" ]]; then
  # Windows venv layout
  PYTHON="${BACKEND_DIR}/.venv/Scripts/python.exe"
else
  echo "Error: backend venv not found at ${BACKEND_DIR}/.venv"
  echo "Run: cd backend && python -m venv .venv && pip install -r requirements.txt"
  exit 1
fi

"$PYTHON" "${BACKEND_DIR}/scripts/export_openapi.py" "$SPEC_PATH"
echo "  -> ${SPEC_PATH}"

# ── Step 2: Run Orval ────────────────────────────────────────────────────────

echo "Generating TypeScript types and React Query hooks..."
cd "$FRONTEND_DIR"
pnpm orval

# ── Step 3: Format generated files ───────────────────────────────────────────

echo "Formatting generated files with Prettier..."
pnpm prettier --write src/api/generated/

echo "Done! Generated files in frontend/src/api/generated/"
