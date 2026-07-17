"""Column-scope the request-path write access on public.users.

A user's platform role (``users.role``) is assigned only through the
capability-gated endpoint ``PATCH /admin/users/{id}/platform-role``, which runs
on the system engine (``app_admin``). Make the database match that intent:

* UPDATE — the request-path floors (``app_guild_base``, ``platform_base``,
  ``app_user``) hold a column-scoped UPDATE covering every ``users`` column
  except ``role`` instead of a table-wide UPDATE. The ORM emits only changed
  columns, so self-update / profile / preference / verification writes are
  unaffected.
* INSERT — kept on ``app_guild_base`` (the guild admin create-user endpoint,
  which always creates a plain member) and revoked from ``platform_base``. A
  RESTRICTIVE policy pins any request-path insert to ``role = 'member'``.
* DELETE — user rows are removed only on the system engine; the unused DELETE
  is revoked from both request floors.

``app_admin`` (BYPASSRLS system engine) is unchanged and still seeds the
bootstrap owner and handles registration. Mirrors the column-scoping already
applied to ``public.guilds`` (0138) and the billing columns (0134).
"""

from alembic import op
from sqlalchemy import text

from app.core.config import settings

revision = "20260717_0144"
down_revision = "20260716_0143"
branch_labels = None
depends_on = None

_APP_GUILD_BASE = "app_guild_base"
_APP_USER = "app_user"


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def _user_columns_except_role(conn) -> list[str]:
    """Every ``public.users`` column other than ``role``, read from the catalog
    at this revision so the grant matches the table exactly."""
    rows = (
        conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'users' "
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
    col_list = ", ".join(f'"{c}"' for c in _user_columns_except_role(conn))

    statements = [
        f'REVOKE UPDATE, DELETE ON TABLE public.users FROM "{_APP_GUILD_BASE}"',
        f'REVOKE INSERT, UPDATE, DELETE ON TABLE public.users FROM "{base}"',
        f'REVOKE UPDATE ON TABLE public.users FROM "{_APP_USER}"',
        f'GRANT UPDATE ({col_list}) ON TABLE public.users TO "{_APP_GUILD_BASE}"',
        f'GRANT UPDATE ({col_list}) ON TABLE public.users TO "{base}"',
        f'GRANT UPDATE ({col_list}) ON TABLE public.users TO "{_APP_USER}"',
        "DROP POLICY IF EXISTS users_request_insert_member_only ON public.users",
        "CREATE POLICY users_request_insert_member_only ON public.users "
        "AS RESTRICTIVE FOR INSERT TO public WITH CHECK (role = 'member')",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    base = _platform_base()
    statements = [
        "DROP POLICY IF EXISTS users_request_insert_member_only ON public.users",
        f'REVOKE UPDATE ON TABLE public.users FROM "{_APP_GUILD_BASE}"',
        f'REVOKE UPDATE ON TABLE public.users FROM "{base}"',
        f'REVOKE UPDATE ON TABLE public.users FROM "{_APP_USER}"',
        f'GRANT INSERT, UPDATE, DELETE ON TABLE public.users TO "{_APP_GUILD_BASE}"',
        f'GRANT INSERT, UPDATE, DELETE ON TABLE public.users TO "{base}"',
        f'GRANT UPDATE ON TABLE public.users TO "{_APP_USER}"',
    ]
    for statement in statements:
        op.execute(statement)
