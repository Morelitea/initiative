"""announcements are written where they are managed

Announcements and their pictures are written under the platform tier that
manages them rather than on the system engine, and the registries
(``app.db.system_grants``, ``app.db.public_rls``) record the result.

* ``announcements``: each tier holding ``announcements.manage`` is granted
  ``INSERT``, ``UPDATE`` and ``DELETE``, and ``USAGE`` on the id sequence. It
  reads through the platform floor as before. The ``announcements_manage``
  policy that admits it to every row is the registry's to render at boot.
* ``announcement_images``: the same tiers are granted ``INSERT``, ``UPDATE``
  and ``DELETE``, under ``announcement_images_manage``.
* ``guilds`` and ``guild_administration`` gain a ``SELECT`` policy for the
  tiers holding ``guilds.manage`` (``guilds_manage_read``,
  ``guild_administration_guilds_manage_read``). The platform floor already
  holds ``SELECT`` on both, so no grant changes; the policies are the
  registry's to render at boot.

No rows move.

Revision ID: 20260923_0365
Revises: 20260923_0364
Create Date: 2026-09-23
"""

from alembic import op

from app.core.capabilities import Capability, roles_with_capability
from app.core.config import settings

revision = "20260923_0365"
down_revision = "20260923_0364"
branch_labels = None
depends_on = None

#: The tier roles holding ``announcements.manage``, as the capability registry
#: spells them.
AUTHORS: tuple[str, ...] = tuple(
    sorted(
        f"{settings.PLATFORM_ROLE_PREFIX}platform_{role.value}"
        for role in roles_with_capability(Capability.ANNOUNCEMENTS_MANAGE)
    )
)

WRITES = "INSERT, UPDATE, DELETE"
TABLES = ("announcements", "announcement_images")

#: Policies the registry renders at boot. The revision this reverts to names
#: none of them, so a downgrade removes them.
RENDERED_POLICIES: tuple[tuple[str, str], ...] = (
    ("announcements_manage", "announcements"),
    ("announcement_images_manage", "announcement_images"),
    ("guilds_manage_read", "guilds"),
    ("guild_administration_guilds_manage_read", "guild_administration"),
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
    for role in AUTHORS:
        for table in TABLES:
            _on_role(role, f'GRANT {WRITES} ON public.{table} TO "{role}"')
        _on_role(
            role,
            f'GRANT USAGE, SELECT ON SEQUENCE public.announcements_id_seq TO "{role}"',
        )


def downgrade() -> None:
    """Take the writes back and drop the policies the registry rendered for
    them; the system engine writes announcements again."""
    for policy, table in RENDERED_POLICIES:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON public.{table}")
    for role in AUTHORS:
        _on_role(
            role,
            f'REVOKE ALL ON SEQUENCE public.announcements_id_seq FROM "{role}"',
        )
        for table in TABLES:
            _on_role(role, f'REVOKE {WRITES} ON public.{table} FROM "{role}"')
