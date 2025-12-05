"""Track the preferred guild order on memberships.

Revision ID: 20240813_0014
Revises: 20240812_0013
Create Date: 2024-08-13 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20240813_0014"
down_revision: Union[str, None] = "20240812_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "guild_memberships",
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )

    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    guild_id,
                    user_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY user_id
                        ORDER BY joined_at ASC, guild_id ASC
                    ) - 1 AS desired_position
                FROM guild_memberships
            )
            UPDATE guild_memberships AS gm
            SET position = ranked.desired_position
            FROM ranked
            WHERE gm.guild_id = ranked.guild_id
              AND gm.user_id = ranked.user_id
            """
        )
    )


def downgrade() -> None:
    op.drop_column("guild_memberships", "position")

