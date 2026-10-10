"""a plug-in can be for the operations community

- ``plugin_service_registrations.operations_only``: the deployment offers this
  plug-in only to its operations community (``app_settings.operations_guild_id``),
  and an install anywhere else is not live. A deployment fact, set beside
  ``mandatory``.
- The install floor, ``plugin_install_base``, reads ``operations_only``: the
  install standing asks whether its registration is live, and the rule now
  reads it. A column grant beside the ones revisions 0379, 0387, 0388, 0393
  and 0437 gave it.

Revision ID: 20261010_0481
Revises: 20261009_0480
Create Date: 2026-10-09
"""

import sqlalchemy as sa
from alembic import op

revision = "20261010_0481"
down_revision = "20261009_0480"
branch_labels = None
depends_on = None

REGISTRATIONS = "plugin_service_registrations"


def upgrade() -> None:
    op.add_column(
        REGISTRATIONS,
        sa.Column(
            "operations_only",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    op.execute(
        f"GRANT SELECT (operations_only) ON public.{REGISTRATIONS} "
        "TO plugin_install_base"
    )


def downgrade() -> None:
    op.execute(
        f"REVOKE SELECT (operations_only) ON public.{REGISTRATIONS} "
        "FROM plugin_install_base"
    )
    op.drop_column(REGISTRATIONS, "operations_only")
