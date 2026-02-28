#!/bin/sh
set -e

# Default to UID/GID 1000 if not specified
APP_UID="${PUID:-1000}"
APP_GID="${PGID:-1000}"

# Validate PUID/PGID are positive integers and not root
case "$APP_UID" in
  ''|*[!0-9]*) echo "ERROR: PUID must be a positive integer, got: '$APP_UID'" >&2; exit 1 ;;
esac
case "$APP_GID" in
  ''|*[!0-9]*) echo "ERROR: PGID must be a positive integer, got: '$APP_GID'" >&2; exit 1 ;;
esac
if [ "$APP_UID" -eq 0 ] || [ "$APP_GID" -eq 0 ]; then
  echo "ERROR: PUID and PGID must not be 0 (root)" >&2; exit 1
fi

# Create group with requested GID (skip if GID already exists)
if ! getent group "$APP_GID" >/dev/null 2>&1; then
    addgroup --system --gid "$APP_GID" app
fi

# Create user with requested UID (skip if UID already exists)
if ! getent passwd "$APP_UID" >/dev/null 2>&1; then
    # Resolve the group name for the target GID
    APP_GROUP=$(getent group "$APP_GID" | cut -d: -f1)
    adduser --system --uid "$APP_UID" --ingroup "$APP_GROUP" --no-create-home app
fi

# Ensure uploads directory is writable
chown -R "$APP_UID:$APP_GID" /app/uploads

# Run the command as the requested UID (numeric avoids name-resolution issues)
exec gosu "$APP_UID" "$@"
