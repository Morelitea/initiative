"""Self-service guild reorder via a SECURITY DEFINER function.

``PUT /guilds/order`` lets a user reorder their own guilds. It runs in PERSONAL
mode (no guild context), so it updates ``guild_memberships.position`` with no
``current_guild_id`` set. The ``guild_memberships_update`` RLS policy only admits
``guild_id = current_guild_id`` (plus, in Phase 1, a standing ``is_superadmin``
bypass that is being removed) — personal mode matches neither, so a direct UPDATE
silently touches 0 rows for EVERY platform role.

Rather than relax the policy (which would let a member rewrite *any* column of
their membership row — e.g. self-promote ``role``), add a narrow ``SECURITY
DEFINER`` function that updates ONLY ``position`` and ONLY for the caller's own
``user_id``. It is the SAME path for every platform tier (member … owner): no
role depends on a standing all-guild bypass. EXECUTE is granted to
``platform_base`` (the floor every platform tier inherits) and to ``app_user``,
and revoked from PUBLIC.

The role names are cluster-global and carry ``settings.PLATFORM_ROLE_PREFIX``
(empty in prod/dev, ``test_<worker>_`` under the suite); the function itself is
per-database so it needs no prefix. Read the prefix at apply time, mirroring the
platform-role migration (0106).

Revision ID: 20260616_0107
Revises: 20260615_0106
Create Date: 2026-06-16
"""

import string

from alembic import op

from app.core.config import settings

revision = "20260616_0107"
down_revision = "20260615_0106"
branch_labels = None
depends_on = None

# Explicit allow-list (letters, digits, underscore) — the prefix is interpolated
# into role-name SQL, so reject anything that isn't a bare role-name character.
_ALLOWED_PREFIX_CHARS = frozenset(string.ascii_letters + string.digits + "_")

_FN = "public.reorder_guild_memberships(integer, integer[])"


def _platform_base() -> str:
    prefix = settings.PLATFORM_ROLE_PREFIX
    if not set(prefix) <= _ALLOWED_PREFIX_CHARS:
        raise ValueError(f"unsafe PLATFORM_ROLE_PREFIX for role DDL: {prefix!r}")
    return f"{prefix}platform_base"


def upgrade() -> None:
    # Sets position = (1-based ordinality) - 1 for each membership named in
    # p_guild_ids, scoped to the caller's own rows. The caller passes the full
    # final order of their memberships, so every one gets a fresh 0-based position.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.reorder_guild_memberships(
            p_user_id integer, p_guild_ids integer[]
        )
        RETURNS void
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path TO 'public'
        AS $function$
            UPDATE guild_memberships gm
            SET position = ord.idx - 1
            FROM unnest(p_guild_ids) WITH ORDINALITY AS ord(guild_id, idx)
            WHERE gm.user_id = p_user_id AND gm.guild_id = ord.guild_id;
        $function$
        """
    )
    op.execute(f"REVOKE EXECUTE ON FUNCTION {_FN} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_FN} TO app_user")
    base = _platform_base()
    op.execute(
        f"""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{base}') THEN
                GRANT EXECUTE ON FUNCTION {_FN} TO "{base}";
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {_FN}")
