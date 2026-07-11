"""Rename the platform ``admin`` tier to ``operator``.

The platform privilege ladder's second-from-top tier shared the word "admin"
with the *guild* admin role, which was a persistent source of confusion. This
renames it to ``operator`` at every level that stores the word:

* the ``public.user_role`` enum value ``'admin'`` -> ``'operator'`` (existing
  ``users.role`` rows follow automatically — enum labels are referenced by OID);
* the cluster-global Postgres role ``platform_admin`` -> ``platform_operator``
  (RLS policies that bind ``TO platform_admin`` follow the rename by OID, so no
  policy needs to be redefined).

Guild admin (``GuildRole.admin`` / the ``current_guild_role='admin'`` RLS leg)
is deliberately untouched.

Revision ID: 20260710_0139
Revises: 20260709_0138
Create Date: 2026-07-10
"""

from __future__ import annotations

import string

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "20260710_0139"
down_revision = "20260709_0138"
branch_labels = None
depends_on = None


# Prefix defense-in-depth (operator/test config, never user input): an explicit
# allow-list of role-name characters so a stray quote can't break out of DDL.
# Frozen copy of the baseline helper — migrations are immutable records and must
# not drift if the prefix logic ever changes.
_ALLOWED_PREFIX_CHARS = frozenset(string.ascii_letters + string.digits + "_")


def _platform_prefix() -> str:
    """The platform-role prefix, read from settings at APPLY time (the test
    suite sets it before running migrations; empty in prod/dev)."""
    from app.core.config import settings

    prefix = settings.PLATFORM_ROLE_PREFIX
    if not set(prefix) <= _ALLOWED_PREFIX_CHARS:
        raise ValueError(f"unsafe PLATFORM_ROLE_PREFIX for role DDL: {prefix!r}")
    return prefix


def _rename_enum_value(connection, old: str, new: str) -> None:
    """Rename a ``public.user_role`` label if the rename is still pending."""
    connection.execute(
        text(
            f"""
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_enum e
                    JOIN pg_type t ON t.oid = e.enumtypid
                    WHERE t.typname = 'user_role' AND e.enumlabel = '{old}'
                ) AND NOT EXISTS (
                    SELECT 1 FROM pg_enum e
                    JOIN pg_type t ON t.oid = e.enumtypid
                    WHERE t.typname = 'user_role' AND e.enumlabel = '{new}'
                ) THEN
                    ALTER TYPE public.user_role RENAME VALUE '{old}' TO '{new}';
                END IF;
            END $$;
            """
        )
    )


def _rename_role(connection, old: str, new: str) -> None:
    """Rename a cluster-global role if it exists and the target is free.

    ``ALTER ROLE ... RENAME`` preserves every GRANT and RLS-policy membership
    (they reference the role by OID), so the ``TO platform_admin`` policies in
    the public schema follow automatically.
    """
    connection.execute(
        text(
            f"""
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{old}')
                   AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{new}') THEN
                    ALTER ROLE "{old}" RENAME TO "{new}";
                END IF;
            END $$;
            """
        )
    )


def upgrade() -> None:
    connection = op.get_bind()
    prefix = _platform_prefix()

    _rename_enum_value(connection, "admin", "operator")
    _rename_role(
        connection,
        f"{prefix}platform_admin",
        f"{prefix}platform_operator",
    )


def downgrade() -> None:
    connection = op.get_bind()
    prefix = _platform_prefix()

    _rename_role(
        connection,
        f"{prefix}platform_operator",
        f"{prefix}platform_admin",
    )
    _rename_enum_value(connection, "operator", "admin")
