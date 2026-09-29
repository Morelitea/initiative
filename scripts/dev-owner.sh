#!/usr/bin/env bash
# The dev platform owner the app seeds on first boot. Sourced by every dev
# script that starts, migrates or seeds the app, so they all sign in as the same
# account:
#
#   . "$SCRIPT_DIR/dev-owner.sh"
#
# A value already in the environment wins.
export FIRST_OWNER_EMAIL="${FIRST_OWNER_EMAIL:-admin@example.com}"
export FIRST_OWNER_PASSWORD="${FIRST_OWNER_PASSWORD:-changeme}"
export FIRST_OWNER_FULL_NAME="${FIRST_OWNER_FULL_NAME:-Admin User}"
