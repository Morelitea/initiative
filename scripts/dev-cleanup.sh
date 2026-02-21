#!/usr/bin/env bash
# Stop dev servers and remove seeded dev data
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Stopping dev servers..."

# Stop backend (uvicorn on port 8000)
if command -v lsof &>/dev/null; then
    lsof -ti:8000 2>/dev/null | xargs kill 2>/dev/null || true
elif command -v fuser &>/dev/null; then
    fuser -k 8000/tcp 2>/dev/null || true
fi
# Also kill by process name as fallback
pkill -f "uvicorn app.main:app" 2>/dev/null || true

# Stop frontend (Vite on port 5173)
if command -v lsof &>/dev/null; then
    lsof -ti:5173 2>/dev/null | xargs kill 2>/dev/null || true
elif command -v fuser &>/dev/null; then
    fuser -k 5173/tcp 2>/dev/null || true
fi
# Also kill by process name as fallback
pkill -f "vite" 2>/dev/null || true

# Give processes a moment to shut down
sleep 1

echo "Servers stopped."

cd "$SCRIPT_DIR/../backend"

# Dev superuser defaults
export FIRST_SUPERUSER_EMAIL="${FIRST_SUPERUSER_EMAIL:-admin@example.com}"
export FIRST_SUPERUSER_PASSWORD="${FIRST_SUPERUSER_PASSWORD:-changeme}"
export FIRST_SUPERUSER_FULL_NAME="${FIRST_SUPERUSER_FULL_NAME:-Admin User}"

source .venv/bin/activate
python "$SCRIPT_DIR/seed_dev_data.py" --clean
