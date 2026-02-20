#!/usr/bin/env bash
# Stop dev servers and remove seeded dev data
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Stop backend (uvicorn on port 8000)
# Stop backend (uvicorn on port 8000)
lsof -ti:8000 2>/dev/null | { xargs kill 2>/dev/null || true; }
# Stop frontend (Vite on port 5173)
lsof -ti:5173 2>/dev/null | { xargs kill 2>/dev/null || true; }

cd "$SCRIPT_DIR/../backend"

# Dev superuser defaults
export FIRST_SUPERUSER_EMAIL="${FIRST_SUPERUSER_EMAIL:-admin@example.com}"
export FIRST_SUPERUSER_PASSWORD="${FIRST_SUPERUSER_PASSWORD:-changeme}"
export FIRST_SUPERUSER_FULL_NAME="${FIRST_SUPERUSER_FULL_NAME:-Admin User}"

source .venv/bin/activate
python "$SCRIPT_DIR/seed_dev_data.py" --clean
