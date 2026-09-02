"""Take ``public.users`` away from the guild-routed request path.

Everything a guild-routed session needs of a person is in
``public.guild_member_profiles`` (0220), and it reads it from there now. So the
table itself goes: ``app_guild_base`` — what every ``guild_<id>`` and
``guild_<id>_ro`` role inherits its shared-table access from — is left holding
nothing on ``public.users``, at the table level or on any column.

That takes back two grants:

* the table-wide SELECT, which reached every column of every account row;
* the column-scoped UPDATE from 0144, which covered every column but ``role``.
  Nothing guild-routed has written the table since 0202 scoped writes to the
  caller's own row — an account is edited on the platform path (``/users/me``,
  ``platform_base``) or by the system engine.

The sequence grant goes with them: it was there for the guild-admin
create-user endpoint, whose INSERT 0202 already removed.

The two policies naming the role are dropped in the same breath. A policy on a
role with no privilege decides nothing, and leaving them would have the catalog
describing access that is not there.

``platform_base`` (own row), the platform tiers and ``app_admin`` are
untouched.

Revision ID: 20260904_0221
Revises: 20260904_0220
Create Date: 2026-09-02
"""

from alembic import op
from sqlalchemy import text

revision = "20260904_0221"
down_revision = "20260904_0220"
branch_labels = None
depends_on = None

ROLE = "app_guild_base"


def _user_columns(conn) -> list[str]:
    """Every ``public.users`` column, read from the catalog at this revision so
    the revoke matches the table exactly."""
    return list(
        conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'users' "
                "ORDER BY column_name"
            )
        )
        .scalars()
        .all()
    )


def upgrade() -> None:
    conn = op.get_bind()
    columns = ", ".join(f'"{column}"' for column in _user_columns(conn))
    statements = [
        # Column privileges outlive a table-level revoke, so both are named.
        f"REVOKE ALL PRIVILEGES ({columns}) ON TABLE public.users FROM {ROLE}",
        f"REVOKE ALL PRIVILEGES ON TABLE public.users FROM {ROLE}",
        f"REVOKE ALL PRIVILEGES ON SEQUENCE public.users_id_seq FROM {ROLE}",
        f"DROP POLICY IF EXISTS users_{ROLE}_read ON public.users",
        f"DROP POLICY IF EXISTS users_{ROLE}_self_update ON public.users",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    conn = op.get_bind()
    writable = ", ".join(
        f'"{column}"' for column in _user_columns(conn) if column != "role"
    )
    current_user_id = "NULLIF(current_setting('app.current_user_id', true), '')::int"
    statements = [
        f"GRANT SELECT ON TABLE public.users TO {ROLE}",
        f"GRANT UPDATE ({writable}) ON TABLE public.users TO {ROLE}",
        f"GRANT SELECT, USAGE ON SEQUENCE public.users_id_seq TO {ROLE}",
        f"CREATE POLICY users_{ROLE}_read ON public.users "
        f"FOR SELECT TO {ROLE} USING (true)",
        f"CREATE POLICY users_{ROLE}_self_update ON public.users "
        f"FOR UPDATE TO {ROLE} "
        f"USING (id = {current_user_id}) WITH CHECK (id = {current_user_id})",
    ]
    for statement in statements:
        op.execute(statement)
