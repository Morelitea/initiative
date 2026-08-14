"""app service delegation jwks

Gives a registration somewhere to hold the public half of the key its app signs
delegation tokens with, as a JWKS so the app can rotate the way we do — two
entries in one set while tokens signed by the first drain out.

The row is already the operator-owned statement of trust about an app, so the
key that identifies that app belongs on it. Nullable, and null everywhere on
arrival: the deployment-wide ``AUTO_DELEGATION_PUBLIC_KEY_PEM`` remains the
verification source until the resolver switch, which is a separate change.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260814_0177"
down_revision = "20260813_0176"
branch_labels = None
depends_on = None

TABLE = "app_service_registrations"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "delegation_jwks", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column(TABLE, "delegation_jwks")
