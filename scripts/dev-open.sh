#!/usr/bin/env bash
# Open the app in a browser once there is actually something behind it.
#
# The SPA and the API come up in separate processes — under the VSCode launch
# config the debug session owns the API and only starts after the setup tasks
# finish — so this polls both and opens the browser when they answer. Vite's own
# --open fires the moment Vite is listening, seconds before the API exists,
# which lands the app on its "no server" screen.
set -e
# This checkout's ports — the URLs below have to point at the servers this
# launch started, not at whatever holds the default pair.
. "$(cd "$(dirname "$0")" && pwd)/dev-ports.sh"
[ -n "${DEV_BACKEND_PORT:-}" ] || exit 1
APP_URL="${DEV_APP_URL:-http://localhost:$DEV_FRONTEND_PORT}"
API_URL="${DEV_API_URL:-http://localhost:$DEV_BACKEND_PORT/api/v1/version}"
TIMEOUT="${DEV_OPEN_TIMEOUT:-180}"

open_url() {
    local url="$1"
    if command -v wslview > /dev/null 2>&1; then
        wslview "$url" > /dev/null 2>&1        # WSL: hands off to the Windows browser
    elif command -v xdg-open > /dev/null 2>&1; then
        xdg-open "$url" > /dev/null 2>&1
    elif command -v open > /dev/null 2>&1; then
        open "$url" > /dev/null 2>&1           # macOS
    else
        echo "No browser opener found — open $url yourself." >&2
        return 1
    fi
}

# Printed before the first poll: the VSCode task watches for this line to know
# it can move on and start the API, which is the thing being waited for here.
echo "Waiting for the app at $APP_URL (API: $API_URL)..."

deadline=$((SECONDS + TIMEOUT))
while [ "$SECONDS" -lt "$deadline" ]; do
    if curl -sf -o /dev/null --max-time 2 "$API_URL" \
        && curl -sf -o /dev/null --max-time 2 "$APP_URL"; then
        echo "Opening $APP_URL"
        open_url "$APP_URL" || true
        exit 0
    fi
    sleep 1
done

echo "Gave up after ${TIMEOUT}s — open $APP_URL once the servers are up." >&2
exit 1
