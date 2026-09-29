"""an install names by reference

An installed app knows each person, and its community, by a reference minted
for its own install (``identity_refs`` rows with ``purpose = 'app'`` and the
install as the sector). Its requests name people that way and its responses
are written that way, so its own request reads and mints those references on
its routed session rather than on the system engine.

The install floor, ``app_install_base``, gains ``SELECT`` and ``INSERT`` on
``public.identity_refs`` and ``USAGE`` on its id sequence, and nothing else on
it. The policies that hold both to the routed install's own sector are
rendered from ``app.db.public_rls`` at boot, like every shared table's.

Revision ID: 20260924_0383
Revises: 20260924_0382
Create Date: 2026-09-24
"""

from alembic import op

revision = "20260924_0383"
down_revision = "20260924_0382"
branch_labels = None
depends_on = None

TABLE = "public.identity_refs"
SEQUENCE = "public.identity_refs_id_seq"

#: The policies ``app.db.public_rls`` renders for the install floor on this
#: table, dropped with the grants on the way down.
_POLICIES = ("install_reads_its_sector", "install_mints_in_its_sector")


def upgrade() -> None:
    op.execute(f"GRANT SELECT, INSERT ON TABLE {TABLE} TO app_install_base")
    op.execute(f"GRANT USAGE ON SEQUENCE {SEQUENCE} TO app_install_base")


def downgrade() -> None:
    for name in _POLICIES:
        op.execute(f"DROP POLICY IF EXISTS {name} ON {TABLE}")
    op.execute(f"REVOKE USAGE ON SEQUENCE {SEQUENCE} FROM app_install_base")
    op.execute(f"REVOKE SELECT, INSERT ON TABLE {TABLE} FROM app_install_base")
