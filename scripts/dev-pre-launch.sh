#!/usr/bin/env bash
# Orchestrate the dev environment startup chain. Equivalent of the VSCode dev:setup
# task chain: db -> migrate -> seed -> backend (bg) -> frontend (bg) -> browser.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

docker-compose up db -d --wait
bash scripts/dev-migrate.sh
bash scripts/dev-seed.sh

# Start the backend in the background (uvicorn with --reload, port-cleanup built in).
nohup bash scripts/dev-backend.sh > /tmp/initiative-backend.log 2>&1 &

# Start the frontend in the background (Vite, port-cleanup built in).
nohup bash scripts/dev-frontend.sh > /tmp/initiative-frontend.log 2>&1 &

# Best-effort browser open once Vite is up.
( sleep 3 && bash scripts/dev-open-browser.sh ) &

echo
echo "Dev environment starting:"
echo "  Backend:  http://localhost:8000   (logs: /tmp/initiative-backend.log)"
echo "  Frontend: http://localhost:5173   (logs: /tmp/initiative-frontend.log)"
echo "  Stop:     run the 'dev:cleanup' Zed task (or bash scripts/dev-cleanup.sh)"
