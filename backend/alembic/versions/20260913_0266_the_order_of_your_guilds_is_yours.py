"""The order of your guild list is yours to set

Reordering the guild list is a personal action. This migration lets callers
update the position of their own guild memberships while keeping all other
membership fields unchanged.

It also removes the obsolete reorder helper now that ordinary membership
updates persist the requested order.

Revision ID: 20260913_0266
Revises: 20260913_0265
Create Date: 2026-09-13
"""

from alembic import op
from sqlalchemy import text

from app.core.config import settings

revision = "20260913_0266"
down_revision = "20260913_0265"
branch_labels = None
depends_on = None

# NULLIF-guarded session-variable read (see CLAUDE.md §5): an unset context
# leaves the value empty, and a bare ''::int would raise rather than fail the
# policy.
_CURRENT_USER_ID = "NULLIF(current_setting('app.current_user_id', true), '')::int"
_CURRENT_GUILD_ID = "NULLIF(current_setting('app.current_guild_id', true), '')::int"

#: The one membership column a request writes.
_REQUEST_COLUMN = "position"

_FUNCTION_NAME = "public.reorder_guild_memberships"
_FUNCTION = f"{_FUNCTION_NAME}(integer, integer[])"


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
    base = _platform_base()
    # A table-level REVOKE of UPDATE takes the column-level grants with it, so
    # this leaves exactly the one column granted below.
    statements = [
        "REVOKE UPDATE ON TABLE public.guild_memberships FROM app_guild_base",
        f'REVOKE UPDATE ON TABLE public.guild_memberships FROM "{base}"',
        f"GRANT UPDATE ({_REQUEST_COLUMN}) ON TABLE public.guild_memberships "
        "TO app_guild_base",
        f"GRANT UPDATE ({_REQUEST_COLUMN}) ON TABLE public.guild_memberships "
        f'TO "{base}"',
        "DROP POLICY IF EXISTS guild_memberships_update ON public.guild_memberships",
        "CREATE POLICY guild_memberships_update ON public.guild_memberships "
        "FOR UPDATE TO public "
        f"USING (user_id = {_CURRENT_USER_ID}) "
        f"WITH CHECK (user_id = {_CURRENT_USER_ID})",
        f"DROP FUNCTION IF EXISTS {_FUNCTION}",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    conn = op.get_bind()
    base = _platform_base()
    col_list = ", ".join(f'"{c}"' for c in _columns_except_role(conn))

    statements = [
        "DROP POLICY IF EXISTS guild_memberships_update ON public.guild_memberships",
        "CREATE POLICY guild_memberships_update ON public.guild_memberships "
        "FOR UPDATE TO public "
        f"USING (guild_id = {_CURRENT_GUILD_ID}) "
        f"WITH CHECK (guild_id = {_CURRENT_GUILD_ID})",
        f"REVOKE UPDATE ({_REQUEST_COLUMN}) ON TABLE public.guild_memberships "
        "FROM app_guild_base",
        f"REVOKE UPDATE ({_REQUEST_COLUMN}) ON TABLE public.guild_memberships "
        f'FROM "{base}"',
        f"GRANT UPDATE ({col_list}) ON TABLE public.guild_memberships "
        "TO app_guild_base",
        f'GRANT UPDATE ({col_list}) ON TABLE public.guild_memberships TO "{base}"',
        f"""
        CREATE OR REPLACE FUNCTION {_FUNCTION_NAME}(
            p_user_id integer, p_guild_ids integer[]
        ) RETURNS void
        LANGUAGE sql SECURITY DEFINER
        SET search_path TO 'public'
        AS $fn$
            UPDATE guild_memberships gm
            SET position = ord.idx - 1
            FROM unnest(p_guild_ids) WITH ORDINALITY AS ord(guild_id, idx)
            WHERE gm.user_id = p_user_id AND gm.guild_id = ord.guild_id;
        $fn$
        """,
        f"REVOKE ALL ON FUNCTION {_FUNCTION} FROM PUBLIC",
        f"GRANT EXECUTE ON FUNCTION {_FUNCTION} TO app_user",
        f'GRANT EXECUTE ON FUNCTION {_FUNCTION} TO "{base}"',
    ]
    for statement in statements:
        op.execute(statement)
