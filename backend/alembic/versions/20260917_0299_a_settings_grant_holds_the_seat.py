"""A live settings grant answers ``guild_superadmin`` for its window.

The seat was a roster question. A grantee is not a member and never becomes
one, so the rung they hold for the grant's window is recorded on the grant and
read from there.

The body is imported from ``app.db.authorization`` rather than copied — that
module is what every database converges on, re-applied on each boot and diffed
by ``authorization_test``. ``CREATE OR REPLACE`` keeps the OID, so the policies
on ``guild_auth_policies`` pick this up unrewritten.

Revision ID: 20260917_0299
Revises: 20260917_0298
Create Date: 2026-09-17
"""

from alembic import op

from app.db.authorization import GUILD_SUPERADMIN

revision = "20260917_0299"
down_revision = "20260917_0298"
branch_labels = None
depends_on = None


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
    op.execute(GUILD_SUPERADMIN)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("SET LOCAL check_function_bodies = false")
    op.execute(_WITHOUT_THE_GRANT_LEG)
