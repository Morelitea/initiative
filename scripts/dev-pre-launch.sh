#!/usr/bin/env bash
# Orchestrate the dev environment startup chain. Equivalent of the VSCode dev:setup
# task chain: db -> migrate -> seed -> backend (bg) -> frontend (bg) -> browser.
#
# After launching, this script blocks waiting on the backend and frontend so
# Ctrl+C (SIGINT), kill (SIGTERM), or closing the terminal (SIGHUP) tears
# the dev environment back down via dev-cleanup.sh.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

docker compose up db -d --wait
bash scripts/dev-migrate.sh
bash scripts/dev-seed.sh

# Start the backend in the background (uvicorn with --reload, port-cleanup built in).
nohup bash scripts/dev-backend.sh > /tmp/initiative-backend.log 2>&1 &
BACKEND_PID=$!

# Start the frontend in the background (Vite, port-cleanup built in).
nohup bash scripts/dev-frontend.sh > /tmp/initiative-frontend.log 2>&1 &
FRONTEND_PID=$!

# Best-effort browser open once Vite is up.
( sleep 3 && bash scripts/dev-open-browser.sh ) &

echo
echo "Dev environment starting:"
echo "  Backend:  http://localhost:8000   (logs: /tmp/initiative-backend.log)"
echo "  Frontend: http://localhost:5173   (logs: /tmp/initiative-frontend.log)"
echo "  Stop:     press Ctrl+C in this terminal (or run bash scripts/dev-cleanup.sh)"
echo

# Run dev-cleanup.sh on Ctrl+C / kill / hangup. The guard makes the function
# idempotent so the INT path (trap fires, wait returns, EXIT trap fires) and
# the natural-exit path (children died -> EXIT trap fires) both end in exactly
# one cleanup pass.
cleanup_done=false
cleanup() {
    [ "$cleanup_done" = true ] && return
    cleanup_done=true
    echo
    echo "Stopping dev environment..."
    bash "$SCRIPT_DIR/dev-cleanup.sh"
}
trap cleanup INT TERM HUP EXIT

# Block. `wait` is interruptible — a signal fires the trap above and aborts
# the wait. Disable `set -e` here so a child exiting non-zero doesn't bypass
# the trap on its way out.
set +e
wait "$BACKEND_PID" "$FRONTEND_PID"
