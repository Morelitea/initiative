"""record what an access grant authorises

A grant is now scoped to one authority and is only ever spent on that one.
Existing rows take the ``content`` server default, which is what they already
were; ``billing`` rows cover the external billing account and nothing else.
"""

import sqlalchemy as sa
from alembic import op

from app.models.platform.access_grant import ACCESS_GRANT_PURPOSES

revision = "20260812_0166"
down_revision = "20260812_0165"
branch_labels = None
depends_on = None

_CK = "ck_access_grants_purpose"


def upgrade() -> None:
    op.add_column(
        "access_grants",
        sa.Column(
            "purpose",
            sa.String(length=16),
            nullable=False,
            server_default="content",
        ),
    )
    # No DML backfill: the server default covers every existing row as part of
    # the ALTER, so this never depends on the policies on a FORCE-RLS table.
    op.create_check_constraint(
        _CK, "access_grants", sa.column("purpose").in_(ACCESS_GRANT_PURPOSES)
    )
    op.create_index(
        "ix_access_grants_purpose", "access_grants", ["purpose"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_access_grants_purpose", table_name="access_grants")
    op.drop_constraint(_CK, "access_grants", type_="check")
    op.drop_column("access_grants", "purpose")
