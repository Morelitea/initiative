"""guests take no seat

- ``guild_memberships.guest_until``: when a guest's membership ends, NULL for
  a member. A ``guest`` row must have one.
- ``app_settings.guests_enabled`` (off), ``max_guest_days`` (90) and
  ``demo_mode`` (written from ``DEMO_MODE`` at boot).
- ``public.guest_membership_live()``: whether a guest row admits its holder
  now. ``guild_superadmin()`` reads a membership row through it.
- The install floor, which reads a member token's own membership row by column,
  may read ``guest_until`` and ``role`` too, to ask whether that row is live.

New columns on existing tables with defaults that need no backfill, so RLS
stays as it is.

Revision ID: 20261010_0488
Revises: 20261010_0487
Create Date: 2026-10-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261010_0488"
down_revision = "20261010_0487"
branch_labels = None
depends_on = None

GUEST_MEMBERSHIP_LIVE = """CREATE OR REPLACE FUNCTION public.guest_membership_live(p_until timestamp with time zone, p_role guild_role)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN p_until > now() AND EXISTS (
        SELECT 1
        FROM public.app_settings s
        WHERE s.id = 1
          AND s.guests_enabled
          AND (p_role = 'guest' OR s.demo_mode)
    );
END
$function$
"""

GUILD_SUPERADMIN_AFTER = """CREATE OR REPLACE FUNCTION public.guild_superadmin(p_guild_id integer, p_user_id integer)
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM public.guild_memberships m
        WHERE m.guild_id = p_guild_id
          AND m.user_id = p_user_id
          AND m.role = 'superadmin'
          AND (m.guest_until IS NULL OR public.guest_membership_live(m.guest_until, m.role))
    )
    -- A live superadmin settings grant satisfies the same predicate.
    OR EXISTS (
        SELECT 1
        FROM public.access_grants g
        WHERE g.guild_id = p_guild_id
          AND g.user_id = p_user_id
          AND g.purpose = 'settings'
          AND g.access_level = 'superadmin'
          AND g.status = 'approved' AND g.expires_at > now()
    )
$function$
"""

GUILD_SUPERADMIN_BEFORE = """CREATE OR REPLACE FUNCTION public.guild_superadmin(p_guild_id integer, p_user_id integer)
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM public.guild_memberships m
        WHERE m.guild_id = p_guild_id
          AND m.user_id = p_user_id
          AND m.role = 'superadmin'
    )
    -- A live superadmin settings grant satisfies the same predicate.
    OR EXISTS (
        SELECT 1
        FROM public.access_grants g
        WHERE g.guild_id = p_guild_id
          AND g.user_id = p_user_id
          AND g.purpose = 'settings'
          AND g.access_level = 'superadmin'
          AND g.status = 'approved' AND g.expires_at > now()
    )
$function$
"""


def upgrade() -> None:
    op.add_column(
        "guild_memberships",
        sa.Column("guest_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_guild_memberships_guest_ends",
        "guild_memberships",
        "role <> 'guest' OR guest_until IS NOT NULL",
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "guests_enabled", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column("max_guest_days", sa.Integer(), nullable=False, server_default="90"),
    )
    op.create_check_constraint(
        "ck_app_settings_max_guest_days", "app_settings", "max_guest_days >= 1"
    )
    op.add_column(
        "app_settings",
        sa.Column("demo_mode", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.execute(GUEST_MEMBERSHIP_LIVE)
    op.execute(GUILD_SUPERADMIN_AFTER)
    op.execute(
        "GRANT SELECT (guest_until, role) ON public.guild_memberships"
        " TO plugin_install_base"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE SELECT (guest_until, role) ON public.guild_memberships"
        " FROM plugin_install_base"
    )
    op.execute(GUILD_SUPERADMIN_BEFORE)
    # The shared-table policies that ask it (``member_of_guild``) go with it.
    # Clearing the stamp makes the version being returned to render them again
    # on its boot (``public_rls.apply_public_rls_if_changed``).
    op.execute(
        "DROP FUNCTION IF EXISTS"
        " public.guest_membership_live(timestamptz, public.guild_role) CASCADE"
    )
    op.execute("COMMENT ON SCHEMA public IS NULL")
    op.drop_column("app_settings", "demo_mode")
    op.drop_constraint("ck_app_settings_max_guest_days", "app_settings", type_="check")
    op.drop_column("app_settings", "max_guest_days")
    op.drop_column("app_settings", "guests_enabled")
    conn = op.get_bind()
    op.execute("ALTER TABLE public.guild_memberships NO FORCE ROW LEVEL SECURITY")
    try:
        conn.execute(
            sa.text(
                "DELETE FROM public.guild_memberships WHERE guest_until IS NOT NULL"
            )
        )
    finally:
        op.execute("ALTER TABLE public.guild_memberships FORCE ROW LEVEL SECURITY")
    op.drop_constraint(
        "ck_guild_memberships_guest_ends", "guild_memberships", type_="check"
    )
    op.drop_column("guild_memberships", "guest_until")
