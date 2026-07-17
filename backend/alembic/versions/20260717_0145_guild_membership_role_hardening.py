"""Harden the request-path write access on public.guild_memberships.

A guild membership's ``role`` (admin/member) is changed only through the
guild-admin endpoint ``PATCH /g/{guild_id}/members/{user_id}``, which now runs
on the system engine (``app_admin``). Make the database match:

* UPDATE — revoked from the request-path floors. ``app_guild_base`` (every
  ``guild_<id>`` role) and ``platform_base`` no longer hold UPDATE on
  ``guild_memberships``; only the system engine (and the SECURITY DEFINER
  reorder function, which runs as its owner) writes the table. The role change
  is the only UPDATE that ran under a request role.
* DELETE — kept on ``app_guild_base`` for self-leave, but the policy is
  tightened to the caller's own row (a member may remove only their own
  membership). Revoked from ``platform_base`` (self-leave re-routes into the
  guild role). Guild deletion removes memberships via ON DELETE CASCADE, which
  is FK enforcement and not subject to RLS.
* INSERT — kept on ``app_guild_base`` (the guild-admin create-user endpoint,
  which adds a plain member); a RESTRICTIVE policy pins any request-path insert
  to ``role = 'member'``. Revoked from ``platform_base`` (invite acceptance and
  registration run on the system engine).

``app_admin`` (BYPASSRLS system engine) keeps its full grant. Same shape as the
users.role column-scoping in 0144.
"""

from alembic import op

from app.core.config import settings

revision = "20260717_0145"
down_revision = "20260717_0144"
branch_labels = None
depends_on = None

# NULLIF-guarded session-variable reads (see CLAUDE.md §5): an unset context
# leaves the value empty, and a bare ''::int would fault every PERMISSIVE policy
# on the table.
_CURRENT_USER_ID = "NULLIF(current_setting('app.current_user_id', true), '')::int"
_CURRENT_GUILD_ID = "NULLIF(current_setting('app.current_guild_id', true), '')::int"


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def upgrade() -> None:
    base = _platform_base()
    statements = [
        "REVOKE UPDATE ON TABLE public.guild_memberships FROM app_guild_base",
        f'REVOKE INSERT, UPDATE, DELETE ON TABLE public.guild_memberships FROM "{base}"',
        # Self-leave only: a member may delete their own membership row.
        "DROP POLICY IF EXISTS guild_memberships_delete ON public.guild_memberships",
        "CREATE POLICY guild_memberships_delete ON public.guild_memberships "
        "FOR DELETE TO public "
        f"USING (guild_id = {_CURRENT_GUILD_ID} AND user_id = {_CURRENT_USER_ID})",
        # A request-path insert may only create a plain member.
        "DROP POLICY IF EXISTS guild_memberships_request_insert_member_only "
        "ON public.guild_memberships",
        "CREATE POLICY guild_memberships_request_insert_member_only "
        "ON public.guild_memberships AS RESTRICTIVE FOR INSERT TO public "
        "WITH CHECK (role = 'member')",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    base = _platform_base()
    statements = [
        "DROP POLICY IF EXISTS guild_memberships_request_insert_member_only "
        "ON public.guild_memberships",
        "DROP POLICY IF EXISTS guild_memberships_delete ON public.guild_memberships",
        "CREATE POLICY guild_memberships_delete ON public.guild_memberships "
        "FOR DELETE TO public "
        f"USING (guild_id = {_CURRENT_GUILD_ID})",
        "GRANT UPDATE ON TABLE public.guild_memberships TO app_guild_base",
        f'GRANT INSERT, UPDATE, DELETE ON TABLE public.guild_memberships TO "{base}"',
    ]
    for statement in statements:
        op.execute(statement)
