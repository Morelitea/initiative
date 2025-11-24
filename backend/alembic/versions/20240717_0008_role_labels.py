"""Add customizable role labels.

Revision ID: 20240717_0008
Revises: 20240717_0007
Create Date: 2024-07-17 00:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import json


# revision identifiers, used by Alembic.
revision: str = "20240717_0008"
down_revision: Union[str, None] = "20240717_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_ROLE_LABELS = {
    "admin": "Admin",
    "project_manager": "Project manager",
    "member": "Member",
}


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "role_labels",
            sa.JSON(),
            nullable=False,
            server_default=sa.text(f"'{json.dumps(DEFAULT_ROLE_LABELS)}'::json"),
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "role_labels")
