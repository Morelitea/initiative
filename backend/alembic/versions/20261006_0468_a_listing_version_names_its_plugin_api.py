"""A listing version names the plug-in API contract it needs.

A plug-in is built against a version of the plug-in SDK, which is the plug-in
API contract. Its listing may say which contract it needs as
``min_plugin_api`` (``MAJOR.MINOR``), beside ``min_app_version``; a deployment
refuses to install or upgrade to a version whose contract it does not serve.

``marketplace_listing_versions.min_plugin_api`` holds it. NULL — every version
published so far — runs on any contract. The catalog tables' grants are
table-wide, so no grant changes.

Revision ID: 20261006_0468
Revises: 20261006_0467
Create Date: 2026-10-06
"""

import sqlalchemy as sa
from alembic import op

revision = "20261006_0468"
down_revision = "20261006_0467"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "marketplace_listing_versions",
        sa.Column("min_plugin_api", sa.String(length=32), nullable=True),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("marketplace_listing_versions", "min_plugin_api", schema="public")
