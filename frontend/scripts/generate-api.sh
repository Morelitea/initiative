#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$(dirname "$SCRIPT_DIR")"
SPEC_PATH=""

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from-spec) SPEC_PATH="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if [[ -n "$SPEC_PATH" ]]; then
  echo "Using provided OpenAPI spec: $SPEC_PATH"
  cp "$SPEC_PATH" "${FRONTEND_DIR}/openapi.json"
else
  API_URL="${VITE_API_URL:-http://localhost:8000/api/v1}"
  echo "Fetching OpenAPI spec from ${API_URL}/openapi.json..."
  curl -sf "${API_URL}/openapi.json" -o "${FRONTEND_DIR}/openapi.json"
fi

echo "Generating TypeScript types and React Query hooks..."
cd "$FRONTEND_DIR"
pnpm orval

echo "Done! Generated files in src/api/generated/"
