#!/usr/bin/env bash
# Orchestrate the dev environment startup chain. Equivalent of the VSCode dev:setup
# task chain: db -> migrate -> seed -> backend (bg) -> frontend (bg) -> browser.
#
# Cleanup belongs to a *running* environment. Once both servers are up, every
# exit path tears them down and removes the seeded data: Ctrl+C (SIGINT), kill
# (SIGTERM), closing the terminal (SIGHUP), or either server exiting on its own.
# Interrupting the startup chain before that point leaves the database alone —
# nothing of this launch's is running yet, and the data is wanted for the next
# attempt. A seed cut short that way is cleared at the top of the next launch.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

BACKEND_PID=""
FRONTEND_PID=""
SEED_STATE=".vscode/.dev_seed_ids.json"

# The guard makes the function idempotent so the signal path (trap fires, the
# poll loop below falls through, EXIT trap fires) and the natural-exit path (a
# server died) both end in exactly one cleanup pass.
cleanup_done=false
cleanup() {
    if [ "$cleanup_done" = true ]; then
        return 0
    fi
    cleanup_done=true
    echo
    echo "Stopping dev environment..."
    # Stop the servers this script started, then let dev-cleanup.sh sweep up
    # whatever is still on the ports and remove the seeded data.
    for pid in "$BACKEND_PID" "$FRONTEND_PID"; do
        if [ -n "$pid" ]; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    bash "$SCRIPT_DIR/dev-cleanup.sh" || true
}

# Startup isn't the environment, so stopping it isn't stopping the environment:
# say what was left behind and get out without touching the database.
abort_startup() {
    echo
    echo "Startup interrupted — dev data left in place."
    echo "  To remove it: bash scripts/dev-cleanup.sh"
    exit 130
}
trap abort_startup INT TERM HUP

docker compose up db -d --wait

# A seed that stopped partway left rows the next one would collide with. Clear
# them here, before the migrate below puts the primary guild + superuser back.
if [ -f "$SEED_STATE" ] && grep -q '"seed_incomplete": *true' "$SEED_STATE"; then
    echo "A previous seed was interrupted — clearing the partial data first."
    bash scripts/dev-cleanup.sh --data-only
fi

bash scripts/dev-migrate.sh
bash scripts/dev-seed.sh

# Spawning a server and recording its pid are two statements, and a signal
# landing between them would reach a cleanup that cannot see that server. Note
# the signal instead of acting on it, and let the check below run the teardown
# once both pids are recorded and the ports are known to be this launch's.
pending_signal=false
trap 'pending_signal=true' INT TERM HUP

# Start the backend in the background (uvicorn with --reload, port-cleanup built in).
nohup bash scripts/dev-backend.sh > /tmp/initiative-backend.log 2>&1 &
BACKEND_PID=$!

# Start the frontend in the background (Vite, port-cleanup built in). --open makes
# Vite open the app in the browser once it's listening; its `open` dependency is
# WSL-aware (launches the Windows browser) and handles macOS/Linux too.
nohup bash scripts/dev-frontend.sh --open > /tmp/initiative-frontend.log 2>&1 &
FRONTEND_PID=$!

# The environment is up and both pids are recorded, so the servers, the ports
# and the seeded data are now this launch's to tear down.
trap cleanup INT TERM HUP EXIT

if [ "$pending_signal" = true ]; then
    exit 0
fi

echo
echo "Dev environment starting:"
echo "  Backend:  http://localhost:8000   (logs: /tmp/initiative-backend.log)"
echo "  Frontend: http://localhost:5173   (logs: /tmp/initiative-frontend.log)"
echo "  Stop:     press Ctrl+C in this terminal (or run bash scripts/dev-cleanup.sh)"
echo

# Block until a signal arrives or one of the servers exits. Poll rather than
# `wait`: plain `wait BACKEND_PID FRONTEND_PID` sits on the survivor when only
# one server goes down, so a backend that died at startup would leave the
# terminal blocked and the cleanup unrun, and `wait -n` (which returns on the
# first exit) needs bash 4.3+ — macOS still ships 3.2. `sleep` is interruptible,
# so a signal fires the trap above promptly. `set -e` is off from here so a
# server exiting non-zero doesn't bypass the trap on its way out.
set +e
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
    sleep 1
done

# Ctrl+C reaches both servers, so both go down and there is nothing to explain.
# One down while the other is still up means that server fell over on its own —
# point at its log, since the environment is about to disappear either way. The
# pause lets the second server finish exiting before the two are told apart.
sleep 0.5
backend_up=false
frontend_up=false
kill -0 "$BACKEND_PID" 2>/dev/null && backend_up=true
kill -0 "$FRONTEND_PID" 2>/dev/null && frontend_up=true
if [ "$cleanup_done" = false ]; then
    if [ "$backend_up" = false ] && [ "$frontend_up" = true ]; then
        echo "Backend exited — see /tmp/initiative-backend.log"
    elif [ "$frontend_up" = false ] && [ "$backend_up" = true ]; then
        echo "Frontend exited — see /tmp/initiative-frontend.log"
    fi
fi
