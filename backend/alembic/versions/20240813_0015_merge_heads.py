"""Merge revision branches.

Revision ID: 20240813_0015
Revises: 20240718_0013, 20240813_0014
Create Date: 2024-08-13 00:10:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "20240813_0015"
down_revision: Union[str, tuple[str, ...], None] = ("20240718_0013", "20240813_0014")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

