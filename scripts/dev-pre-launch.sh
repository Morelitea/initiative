#!/usr/bin/env bash
# Orchestrate the dev environment startup chain. Equivalent of the VSCode dev:setup
# task chain: db -> migrate -> seed -> backend (bg) -> frontend (bg) -> browser.
#
# Cleanup runs on every exit path: Ctrl+C (SIGINT), kill (SIGTERM), closing the
# terminal (SIGHUP), a startup step that fails, or either dev server exiting on
# its own. The trap is armed before the first step so there is no window where a
# signal or an error can leave the environment half-up with its data seeded.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

BACKEND_PID=""
FRONTEND_PID=""

# The guard makes the function idempotent so the signal path (trap fires, `wait`
# returns, EXIT trap fires) and the natural-exit path (a server died, or a
# startup step failed under `set -e`) both end in exactly one cleanup pass.
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
trap cleanup INT TERM HUP EXIT

docker compose up db -d --wait
bash scripts/dev-migrate.sh
bash scripts/dev-seed.sh

# Start the backend in the background (uvicorn with --reload, port-cleanup built in).
nohup bash scripts/dev-backend.sh > /tmp/initiative-backend.log 2>&1 &
BACKEND_PID=$!

# Start the frontend in the background (Vite, port-cleanup built in). --open makes
# Vite open the app in the browser once it's listening; its `open` dependency is
# WSL-aware (launches the Windows browser) and handles macOS/Linux too.
nohup bash scripts/dev-frontend.sh --open > /tmp/initiative-frontend.log 2>&1 &
FRONTEND_PID=$!

echo
echo "Dev environment starting:"
echo "  Backend:  http://localhost:8000   (logs: /tmp/initiative-backend.log)"
echo "  Frontend: http://localhost:5173   (logs: /tmp/initiative-frontend.log)"
echo "  Stop:     press Ctrl+C in this terminal (or run bash scripts/dev-cleanup.sh)"
echo

# Block until a signal arrives or one of the servers exits. `wait -n` returns on
# the FIRST child to exit — plain `wait BACKEND_PID FRONTEND_PID` sits on the
# survivor instead, so a backend that died at startup would leave the terminal
# blocked and the cleanup unrun. `wait` is interruptible: a signal fires the trap
# above and aborts it. `set -e` is off from here so a server exiting non-zero
# doesn't bypass the trap on its way out.
set +e
wait -n

# Ctrl+C reaches both servers, so both go down and there is nothing to explain.
# One down while the other is still up means that server fell over on its own —
# point at its log, since the environment is about to disappear either way. The
# pause lets the second server finish exiting before the two cases are told apart.
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
