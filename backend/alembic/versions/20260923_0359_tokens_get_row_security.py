"""tokens get row security

The last two shared tables without row security gain it, and the registries
(``app.db.system_grants``, ``app.db.public_rls``) record the result.

* ``user_tokens`` (email verification, password reset, device tokens) is read
  and written on the system engine alone, like ``auth_sessions`` and
  ``user_api_keys``. The bare login, both guild floors and the platform floor
  lose every verb on the table and its id sequence; the table is ``ENABLE`` +
  ``FORCE`` with no policy, which the registry records as
  ``FORCED_NO_POLICY``.
* ``push_tokens`` is delivered from on the system engine and registered under
  the owner's platform tier. Both guild floors lose every verb on the table and
  its id sequence; the platform floor keeps its four; the table is ``ENABLE`` +
  ``FORCE``. Its own-row policies for the platform floor are the registry's to
  render at boot, which runs after the migrations and before the app serves.

No rows move: enabling row security changes no data, and the system engine
reads and writes both tables as it did before.

Revision ID: 20260923_0359
Revises: 20260923_0358
Create Date: 2026-09-23
"""

from alembic import op

from app.core.config import settings

revision = "20260923_0359"
down_revision = "20260923_0358"
branch_labels = None
depends_on = None

GUILD_FLOOR = "app_guild_base"
READ_FLOOR = "app_guild_base_ro"
PLATFORM_FLOOR = f"{settings.PLATFORM_ROLE_PREFIX}platform_base"
LOGIN = "app_user"

ALL_VERBS = "SELECT, INSERT, UPDATE, DELETE"

#: (verbs, table, role), revoked on the way up and granted on the way down.
TAKEN_BACK: tuple[tuple[str, str, str], ...] = (
    (ALL_VERBS, "user_tokens", LOGIN),
    (ALL_VERBS, "user_tokens", GUILD_FLOOR),
    ("SELECT", "user_tokens", READ_FLOOR),
    (ALL_VERBS, "user_tokens", PLATFORM_FLOOR),
    (ALL_VERBS, "push_tokens", GUILD_FLOOR),
    ("SELECT", "push_tokens", READ_FLOOR),
)

#: (table, role) whose id-sequence USAGE goes with the table's INSERT.
SEQUENCES_TAKEN_BACK: tuple[tuple[str, str], ...] = (
    ("user_tokens", LOGIN),
    ("user_tokens", GUILD_FLOOR),
    ("user_tokens", PLATFORM_FLOOR),
    ("push_tokens", GUILD_FLOOR),
)

TABLES = ("user_tokens", "push_tokens")

#: Policies the registry renders on ``push_tokens`` at boot. The revision this
#: reverts to names none, so a downgrade removes them.
PUSH_TOKEN_POLICIES = (
    "push_tokens_self_read",
    "push_tokens_self_insert",
    "push_tokens_self_update",
    "push_tokens_self_delete",
)


def _on_role(role: str, statement: str) -> None:
    """Run ``statement`` when ``role`` exists on this cluster."""
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                EXECUTE '{statement}';
            END IF;
        END
        $$;
        """
    )


def _on_sequence(table: str, role: str, action: str) -> None:
    """``GRANT`` or ``REVOKE`` the id sequence of ``table`` for ``role``, when
    both exist on this cluster."""
    clause = (
        "GRANT USAGE, SELECT ON SEQUENCE %s TO %I"
        if action == "GRANT"
        else "REVOKE ALL ON SEQUENCE %s FROM %I"
    )
    op.execute(
        f"""
        DO $$
        DECLARE
            seq text := pg_get_serial_sequence('public.{table}', 'id');
        BEGIN
            IF seq IS NOT NULL
               AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                EXECUTE format('{clause}', seq, '{role}');
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    for verbs, table, role in TAKEN_BACK:
        _on_role(role, f'REVOKE {verbs} ON public.{table} FROM "{role}"')
    for table, role in SEQUENCES_TAKEN_BACK:
        _on_sequence(table, role, "REVOKE")
    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Row security off and the verbs back, as the revision this reverts to
    had them."""
    for policy in PUSH_TOKEN_POLICIES:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON public.push_tokens")
    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
    for table, role in SEQUENCES_TAKEN_BACK:
        _on_sequence(table, role, "GRANT")
    for verbs, table, role in TAKEN_BACK:
        _on_role(role, f'GRANT {verbs} ON public.{table} TO "{role}"')
