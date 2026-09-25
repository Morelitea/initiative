"""an app names its vendor values

An app's manifest may declare a ``vendor`` block: what an operator supplies
once per deployment for the vendor's own client (its id, its secret, its
signing key). Initiative runs the app's connection flows with those values, so
they are kept on the app's registration.

- ``app_service_registrations.vendor_values``: one Fernet ciphertext per field,
  keyed by the field's key.
- ``app_service_registrations.vendor_required``: the keys the listing's
  manifest marks required, as of the last time the registration or its listing
  was written.
- ``app_service_registrations.vendor_ready``: whether every required key holds
  a value, computed by the database. A registration is live only when it is.
- The install floor, ``app_install_base``, reads ``vendor_ready``: the install
  standing asks whether its registration is live. A column grant beside the
  ones revisions 0379, 0387 and 0388 gave it; the values themselves stay the
  system engine's.

Revision ID: 20260925_0393
Revises: 20260924_0392
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260925_0393"
down_revision = "20260924_0392"
branch_labels = None
depends_on = None

REGISTRATIONS = "app_service_registrations"


def upgrade() -> None:
    op.add_column(
        REGISTRATIONS,
        sa.Column(
            "vendor_values",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        REGISTRATIONS,
        sa.Column(
            "vendor_required",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.add_column(
        REGISTRATIONS,
        sa.Column(
            "vendor_ready",
            sa.Boolean(),
            sa.Computed("vendor_values ?& vendor_required", persisted=True),
            nullable=False,
        ),
    )
    op.execute(
        f"GRANT SELECT (vendor_ready) ON public.{REGISTRATIONS} TO app_install_base"
    )


def downgrade() -> None:
    op.execute(
        f"REVOKE SELECT (vendor_ready) ON public.{REGISTRATIONS} FROM app_install_base"
    )
    op.drop_column(REGISTRATIONS, "vendor_ready")
    op.drop_column(REGISTRATIONS, "vendor_required")
    op.drop_column(REGISTRATIONS, "vendor_values")
