"""a declarative app keeps a registration

A declarative app is one whose calls Initiative makes itself, from its
manifest. It keeps a registration for its vendor values, its setup flow and
its switches, but has no location and no keys, so a registration says which
kind of app it is for.

- ``app_service_registrations.kind``: ``container`` or ``declarative``, written
  by the listing apply. Every registration until now is a container's.
- The install floor, ``app_install_base``, reads ``kind``: the install standing
  asks whether its registration is live, and the rule now reads it. A column
  grant beside the ones revisions 0379, 0387, 0388 and 0393 gave it.

Revision ID: 20261001_0437
Revises: 20261001_0436
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from alembic import op

revision = "20261001_0437"
down_revision = "20261001_0436"
branch_labels = None
depends_on = None

REGISTRATIONS = "app_service_registrations"


def upgrade() -> None:
    op.add_column(
        REGISTRATIONS,
        sa.Column(
            "kind",
            sa.String(16),
            server_default="container",
            nullable=False,
        ),
    )
    op.execute(f"GRANT SELECT (kind) ON public.{REGISTRATIONS} TO app_install_base")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT (kind) ON public.{REGISTRATIONS} FROM app_install_base")
    op.drop_column(REGISTRATIONS, "kind")
