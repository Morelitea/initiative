"""A live settings grant answers ``guild_superadmin`` for its window.

The seat was a roster question. A grantee is not a member and never becomes
one, so the rung they hold for the grant's window is recorded on the grant and
read from there.

The body is stated here so this historical revision cannot change when the
live authorization registry changes later. Boot-time repair keeps its current
definition in ``app.db.authorization``. ``CREATE OR REPLACE`` keeps the OID,
so the policies on ``guild_auth_policies`` pick this up unrewritten.

Revision ID: 20260917_0299
Revises: 20260917_0298
Create Date: 2026-09-17
"""

from alembic import op

revision = "20260917_0299"
down_revision = "20260917_0298"
branch_labels = None
depends_on = None


_WITH_THE_GRANT_LEG = """\
CREATE OR REPLACE FUNCTION public.guild_superadmin(p_guild_id integer, p_user_id integer)
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
    -- Or a live settings grant at the same rung. A grantee is not a member, so
    -- the seat they hold for the grant's window is recorded on the grant.
    OR EXISTS (
        SELECT 1
        FROM public.access_grants g
        WHERE g.guild_id = p_guild_id
          AND g.user_id = p_user_id
          AND g.purpose = 'settings'
          AND g.access_level = 'superadmin'
          AND g.status = 'approved'
          AND g.expires_at > now()
    )
$function$

"""


_WITHOUT_THE_GRANT_LEG = """\
CREATE OR REPLACE FUNCTION public.guild_superadmin(p_guild_id integer, p_user_id integer)
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
$function$
"""


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("SET LOCAL check_function_bodies = false")
    op.execute(_WITH_THE_GRANT_LEG)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("SET LOCAL check_function_bodies = false")
    op.execute(_WITHOUT_THE_GRANT_LEG)
