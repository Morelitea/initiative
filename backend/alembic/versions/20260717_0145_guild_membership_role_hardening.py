"""Column-scope the request-path write access on public.guild_memberships.

A guild membership's ``role`` (admin/member) is changed only through the
guild-admin endpoint ``PATCH /g/{guild_id}/members/{user_id}``, which now runs
on the system engine (``app_admin``). Make the database match:

* UPDATE — the request-path floors (``app_guild_base`` — every ``guild_<id>``
  role — and ``platform_base``) hold a column-scoped UPDATE covering every
  ``guild_memberships`` column except ``role`` instead of a table-wide UPDATE.
  A column-scoped UPDATE still satisfies ``SELECT ... FOR UPDATE`` row locks
  (used by the self-leave / last-admin checks), so only a write that names
  ``role`` is refused.
* DELETE — the self-leave policy is scoped to the caller's own row (a member may
  remove only their own membership). Guild deletion removes memberships via
  ON DELETE CASCADE, which is FK enforcement and not subject to RLS.
* INSERT — a RESTRICTIVE policy pins any request-path insert to ``role =
  'member'`` (the guild-admin create-user path adds a plain member).

INSERT/DELETE grants are unchanged (create-user and self-leave run under the
guild role). ``app_admin`` (BYPASSRLS system engine) keeps its full grant. Same
shape as the users.role column-scoping in 0144.
"""

from alembic import op
from sqlalchemy import text

from app.core.config import settings

revision = "20260717_0145"
down_revision = "20260717_0144"
branch_labels = None
depends_on = None

_APP_GUILD_BASE = "app_guild_base"

# NULLIF-guarded session-variable reads (see CLAUDE.md §5): an unset context
# leaves the value empty, and a bare ''::int would fault every PERMISSIVE policy
# on the table.
_CURRENT_USER_ID = "NULLIF(current_setting('app.current_user_id', true), '')::int"
_CURRENT_GUILD_ID = "NULLIF(current_setting('app.current_guild_id', true), '')::int"


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def _columns_except_role(conn) -> list[str]:
    """Every ``public.guild_memberships`` column other than ``role``."""
    rows = (
        conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'guild_memberships' "
                "AND column_name <> 'role' ORDER BY column_name"
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


def upgrade() -> None:
    conn = op.get_bind()
    base = _platform_base()
    col_list = ", ".join(f'"{c}"' for c in _columns_except_role(conn))

    statements = [
        f'REVOKE UPDATE ON TABLE public.guild_memberships FROM "{_APP_GUILD_BASE}"',
        f'REVOKE UPDATE ON TABLE public.guild_memberships FROM "{base}"',
        f"GRANT UPDATE ({col_list}) ON TABLE public.guild_memberships "
        f'TO "{_APP_GUILD_BASE}"',
        f'GRANT UPDATE ({col_list}) ON TABLE public.guild_memberships TO "{base}"',
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
        f'REVOKE UPDATE ON TABLE public.guild_memberships FROM "{_APP_GUILD_BASE}"',
        f'REVOKE UPDATE ON TABLE public.guild_memberships FROM "{base}"',
        f'GRANT UPDATE ON TABLE public.guild_memberships TO "{_APP_GUILD_BASE}"',
        f'GRANT UPDATE ON TABLE public.guild_memberships TO "{base}"',
    ]
    for statement in statements:
        op.execute(statement)
