"""Scope request-path writes on public.users to the caller's own row.

An account belongs to the person it names rather than to a guild or a platform
tier, so a request-path session writes exactly one row: its own.

* SELECT is unchanged and unconditional for the request path — rosters,
  pickers and member management all read other people.
* UPDATE reaches only the row whose ``id`` matches ``app.current_user_id``.
* INSERT keeps no permissive request-path policy at all: accounts are created
  by registration and by invite redemption, both of which run on the system
  engine.
* DELETE was already closed by the ``users_no_delete`` restrictive policy.

``app_admin`` is untouched. It is BYPASSRLS and grant-bounded, and stays the
actor for registration, password resets, email verification and platform user
management.

Mirrors the own-row policy shape ``public.user_avatars`` uses (0201).
"""

from alembic import op

from app.core.config import settings

revision = "20260828_0202"
down_revision = "20260828_0201"
branch_labels = None
depends_on = None


CURRENT_USER_ID = "NULLIF(current_setting('app.current_user_id', true), '')::int"

# The request-path floors. ``app_user`` is the bare login role (a handler that
# has not assumed a scoped role); ``app_guild_base`` is what every ``guild_<id>``
# role inherits its shared-table access from.
_REQUEST_FLOORS = ("app_user", "app_guild_base")


def _platform_tiers() -> list[str]:
    prefix = settings.PLATFORM_ROLE_PREFIX
    return [
        f"{prefix}platform_{tier}"
        for tier in ("support", "moderator", "operator", "owner")
    ]


def upgrade() -> None:
    statements = [
        # The table-wide floors are replaced by a read leg plus an own-row
        # write leg, one pair per request-path role.
        "DROP POLICY IF EXISTS users_app_floor ON public.users",
        "DROP POLICY IF EXISTS users_guild_floor ON public.users",
        # Platform user management runs on the system engine, so the tiers need
        # no write policy of their own; ``users_platform_self`` (own row, TO
        # platform_base) already covers a moderator editing their own account.
        "DROP POLICY IF EXISTS users_platform_manage ON public.users",
    ]
    for role in _REQUEST_FLOORS:
        statements += [
            f"CREATE POLICY users_{role}_read ON public.users "
            f"FOR SELECT TO {role} USING (true)",
            f"CREATE POLICY users_{role}_self_update ON public.users "
            f"FOR UPDATE TO {role} "
            f"USING (id = {CURRENT_USER_ID}) WITH CHECK (id = {CURRENT_USER_ID})",
        ]
    # A guild admin no longer creates accounts, so the request path holds no
    # INSERT privilege on the table either. The restrictive
    # ``users_request_insert_member_only`` policy from 0144 stays as the
    # standing floor on anything that regains one.
    statements.append("REVOKE INSERT ON TABLE public.users FROM app_guild_base")
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    statements = ["GRANT INSERT ON TABLE public.users TO app_guild_base"]
    for role in _REQUEST_FLOORS:
        statements += [
            f"DROP POLICY IF EXISTS users_{role}_read ON public.users",
            f"DROP POLICY IF EXISTS users_{role}_self_update ON public.users",
        ]
    statements += [
        "CREATE POLICY users_app_floor ON public.users TO app_user "
        "USING (true) WITH CHECK (true)",
        "CREATE POLICY users_guild_floor ON public.users TO app_guild_base "
        "USING (true) WITH CHECK (true)",
        "CREATE POLICY users_platform_manage ON public.users FOR UPDATE TO "
        + ", ".join(f'"{tier}"' for tier in _platform_tiers()[1:])
        + " USING (true) WITH CHECK (true)",
    ]
    for statement in statements:
        op.execute(statement)
