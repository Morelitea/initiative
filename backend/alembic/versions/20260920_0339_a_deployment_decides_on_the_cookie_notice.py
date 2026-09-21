"""Whether this deployment shows arriving visitors a cookie notice.

One column, no new table and nothing to carry into one.

``app_settings.cookie_notice_enabled`` -- whether the first-visit notice about
browser storage appears. Defaults false: most deployments are a community's own
server on its own network, where nobody arrives who was not sent, and a notice
nobody needs is just something in the way. A deployment with a public front door
turns it on.

The notice is an acknowledgement rather than a gate -- nothing about the app
changes when it is dismissed -- so switching it on or off takes nothing away and
grants nothing, and a visitor who already dismissed it is not asked again.

``app_settings`` is granted table-wide to the owner tier, so the new column
arrives writable, and no policy references it -- an ``ADD COLUMN`` is not a
policy-bound write, so there is no RLS to lift.

Revision ID: 20260920_0339
Revises: 20260920_0338
Create Date: 2026-09-20
"""

import sqlalchemy as sa
from alembic import op

revision = "20260920_0339"
down_revision = "20260920_0338"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "cookie_notice_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "cookie_notice_enabled")
