"""a container's keys are the deployment's

Every app from the registry is a container, and each deployment that runs one
gives the key set its copy signs with. Until now the registry wrote the
publisher's key set onto the registrations it created, and nothing else could
set keys on those rows. This clears ``jwks`` and ``jwks_uri`` on every
registration whose app facts came from the registry, so each takes the key set
its deployment gives (``APP_SERVICES_CONFIG`` or the settings form) and is not
live until it has one.

The downgrade leaves the rows as they are: the key sets removed were the
publisher's, which no release reads any more.

Revision ID: 20260929_0416
Revises: 20260929_0415
Create Date: 2026-09-29
"""

from alembic import op

revision = "20260929_0416"
down_revision = "20260929_0415"
branch_labels = None
depends_on = None

TABLE = "public.app_service_registrations"


def upgrade() -> None:
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(
            f"UPDATE {TABLE} SET jwks = NULL, jwks_uri = NULL "
            "WHERE source = 'registry' "
            "AND (jwks IS NOT NULL OR jwks_uri IS NOT NULL)"
        )
    finally:
        op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    pass
