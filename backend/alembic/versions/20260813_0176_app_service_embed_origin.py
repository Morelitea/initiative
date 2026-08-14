"""app service embed origin

Splits the one address a registration carried into the two it actually needs:
``base_url`` stays the wire surface Initiative's own server calls, and
``embed_origin`` is where a person's browser loads the app's iframes and
connection pages.

Nullable, and left null everywhere by this migration: an unset column means the
app answers both surfaces at ``base_url``, which is exactly what every existing
registration already does.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260813_0176"
down_revision = "20260813_0175"
branch_labels = None
depends_on = None

TABLE = "app_service_registrations"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column("embed_origin", sa.String(length=1000), nullable=True),
    )


def downgrade() -> None:
    op.drop_column(TABLE, "embed_origin")
