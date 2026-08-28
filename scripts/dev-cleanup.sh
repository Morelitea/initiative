#!/usr/bin/env bash
# Stop dev servers and remove seeded dev data.
#
# This is the teardown path, so it never aborts partway: a missing venv or an
# unreachable database must not leave the servers running or skip the data
# clean. Each step reports what went wrong and the exit code reflects it.
set -o pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

status=0

# PIDs listening on a TCP port, via whichever tool this machine has.
port_pids() {
    if command -v lsof &>/dev/null; then
        lsof -ti:"$1" 2>/dev/null
    elif command -v fuser &>/dev/null; then
        fuser "$1"/tcp 2>/dev/null | tr ' ' '\n'
    fi
}

# Ask the listeners on a port to stop, then force whatever is still holding it.
stop_port() {
    local port="$1" label="$2" pids
    pids=$(port_pids "$port")
    [ -n "$pids" ] || return 0

    echo "  stopping $label on port $port"
    kill $pids 2>/dev/null || true

    # Poll against a wall-clock deadline rather than a fixed iteration count —
    # looking the port up is itself slow enough to stretch a counted loop well
    # past the grace period it was meant to allow.
    local deadline=$((SECONDS + 5))
    while [ "$SECONDS" -lt "$deadline" ]; do
        pids=$(port_pids "$port")
        [ -n "$pids" ] || return 0
        sleep 0.2
    done
    pids=$(port_pids "$port")
    [ -n "$pids" ] || return 0

    echo "  $label did not stop on its own — forcing"
    kill -9 $pids 2>/dev/null || true
}

echo "Stopping dev servers..."
stop_port 8000 "backend"
stop_port 5173 "frontend"

# Fallbacks for servers that are up but not listening yet (killed mid-startup,
# or still binding the port).
pkill -f "uvicorn app.main:app" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true

echo "Servers stopped."

if ! cd "$SCRIPT_DIR/../backend"; then
    echo "Could not enter backend/ — seeded dev data left in place." >&2
    exit 1
fi

# Dev superuser defaults
export FIRST_SUPERUSER_EMAIL="${FIRST_SUPERUSER_EMAIL:-admin@example.com}"
export FIRST_SUPERUSER_PASSWORD="${FIRST_SUPERUSER_PASSWORD:-changeme}"
export FIRST_SUPERUSER_FULL_NAME="${FIRST_SUPERUSER_FULL_NAME:-Admin User}"

if [ ! -f .venv/bin/activate ]; then
    echo "Skipping dev data clean: backend/.venv is missing (run: cd backend && uv sync)." >&2
    exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate
if ! python "$SCRIPT_DIR/seed_dev_data.py" --clean; then
    echo "Dev data clean failed — is the database up? (docker compose up db -d)" >&2
    status=1
fi

exit $status
