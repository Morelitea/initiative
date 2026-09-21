"""Whether this deployment asks arriving visitors about cookies.

One column, no new table and nothing to carry into one.

``app_settings.cookie_consent_enabled`` -- whether the cookie chooser appears on
a first visit. Defaults false: most deployments are a community's own server on
its own network, where nobody arrives who was not sent, and a question nobody
needed is just something in the way. A deployment with a public front door turns
it on.

What somebody answers is kept in their own browser and never reaches this
database. There is no account behind a landing-page visitor to attach it to, and
the answer only governs what that browser loads.

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
            "cookie_consent_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "cookie_consent_enabled")
