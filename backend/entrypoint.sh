#!/bin/sh
set -e

# Default to UID/GID 1000 if not specified
APP_UID="${PUID:-1000}"
APP_GID="${PGID:-1000}"

# Create group and user with the requested UID/GID
if ! getent group app >/dev/null 2>&1; then
    addgroup --system --gid "$APP_GID" app
fi
if ! getent passwd app >/dev/null 2>&1; then
    adduser --system --uid "$APP_UID" --ingroup app --no-create-home app
fi

# Ensure uploads directory is writable
chown -R "$APP_UID:$APP_GID" /app/uploads

# Run the command as the app user
exec gosu app "$@"
