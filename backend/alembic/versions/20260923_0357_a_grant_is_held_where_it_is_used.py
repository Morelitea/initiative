"""a grant is held where it is used

Each verb below is held by a request-path role that no caller exercises; each
goes, and the registries (``app.db.system_grants``, ``app.db.public_rls``)
record the result.

* ``app_service_registrations`` is read and written on the system engine
  alone. The platform owner's direct ``SELECT`` (0169) goes, and with it the
  owner's read policy; the registry records the table as ``FORCED_NO_POLICY``.
* ``guilds`` is created, deleted and purged on the system engine. The guild
  floor's ``DELETE`` goes, and the ``guild_insert`` and ``guild_delete``
  policies with it.
* ``guild_invites`` is previewed, redeemed and scrubbed on the system engine,
  and listed, issued and withdrawn on a routed request. The bare login's
  ``SELECT``, the platform floor's four verbs and the guild floor's ``UPDATE``
  go, and the ``guild_update`` policy with them. The three that remain now name
  the guild floor rather than ``PUBLIC``; that is the registry's to render at
  boot.
* ``guild_memberships`` is left on a routed request, so the platform floor's
  ``DELETE`` goes.
* ``notifications`` is written on a routed request or the system engine, so
  the platform floor's ``INSERT`` goes.
* ``user_avatars`` is changed under a platform tier or on the system engine,
  so the bare login's three writes go; it keeps ``SELECT`` for the serve
  endpoint.
* ``auto_delegation_jti_blocklist`` is read and recorded on the bare login and
  pruned on the system engine, so both floors lose everything, and the read
  floor its ``SELECT``.

Revision ID: 20260923_0357
Revises: 20260923_0356
Create Date: 2026-09-23
"""

from alembic import op

from app.core.config import settings

revision = "20260923_0357"
down_revision = "20260923_0356"
branch_labels = None
depends_on = None

GUILD_FLOOR = "app_guild_base"
READ_FLOOR = "app_guild_base_ro"
PLATFORM_FLOOR = f"{settings.PLATFORM_ROLE_PREFIX}platform_base"
PLATFORM_OWNER = f"{settings.PLATFORM_ROLE_PREFIX}platform_owner"
LOGIN = "app_user"

#: (verbs, table, role), revoked on the way up and granted on the way down.
TAKEN_BACK: tuple[tuple[str, str, str], ...] = (
    ("SELECT", "app_service_registrations", PLATFORM_OWNER),
    ("DELETE", "guilds", GUILD_FLOOR),
    ("SELECT", "guild_invites", LOGIN),
    ("SELECT, INSERT, UPDATE, DELETE", "guild_invites", PLATFORM_FLOOR),
    ("UPDATE", "guild_invites", GUILD_FLOOR),
    ("DELETE", "guild_memberships", PLATFORM_FLOOR),
    ("INSERT", "notifications", PLATFORM_FLOOR),
    ("INSERT, UPDATE, DELETE", "user_avatars", LOGIN),
    ("SELECT, INSERT, UPDATE, DELETE", "auto_delegation_jti_blocklist", GUILD_FLOOR),
    ("SELECT", "auto_delegation_jti_blocklist", READ_FLOOR),
    (
        "SELECT, INSERT, UPDATE, DELETE",
        "auto_delegation_jti_blocklist",
        PLATFORM_FLOOR,
    ),
)

#: (policy, table) the registry no longer names.
DROPPED_POLICIES: tuple[tuple[str, str], ...] = (
    ("app_service_registrations_owner_read", "app_service_registrations"),
    ("guild_insert", "guilds"),
    ("guild_delete", "guilds"),
    ("guild_update", "guild_invites"),
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


def upgrade() -> None:
    for verbs, table, role in TAKEN_BACK:
        _on_role(role, f'REVOKE {verbs} ON public.{table} FROM "{role}"')
    for policy, table in DROPPED_POLICIES:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON public.{table}")


def downgrade() -> None:
    """Give the verbs back. The policies are the registry's: a boot on the
    revision this reverts to renders them again from what it names."""
    for verbs, table, role in TAKEN_BACK:
        _on_role(role, f'GRANT {verbs} ON public.{table} TO "{role}"')
