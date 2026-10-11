"""ranking by engagement can be turned off

Two columns, one question: may search order a community's content by how many
of its members engaged with it lately. ``app_settings`` holds the deployment's
answer and ``guilds`` each community's, and off wins.

Both ship on, and nothing ranks by engagement yet, so an upgrade changes
nothing.

The seat writes its community's answer, so ``app_superadmin`` gets ``UPDATE``
on the new ``guilds`` column beside the switches it already sets.

Revision ID: 20261010_0493
Revises: 20261010_0492
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

revision = "20261010_0493"
down_revision = "20261010_0492"
branch_labels = None
depends_on = None

SEAT_FLOOR = "app_superadmin"

#: (table, column) for every column this revision adds.
COLUMNS = (
    ("app_settings", "engagement_ranking_enabled"),
    ("guilds", "allow_engagement_ranking"),
)


def _on_seat_floor(statement: str) -> None:
    """Run ``statement`` if the seat floor exists: the roles are cluster-global,
    and a database restored beside another deployment's may not carry them."""
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{SEAT_FLOOR}') THEN
                EXECUTE '{statement}';
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    for table, column in COLUMNS:
        op.add_column(
            table,
            sa.Column(
                column, sa.Boolean(), nullable=False, server_default=sa.text("true")
            ),
            schema="public",
        )
    _on_seat_floor(
        f"GRANT UPDATE (allow_engagement_ranking) ON public.guilds TO {SEAT_FLOOR}"
    )


def downgrade() -> None:
    _on_seat_floor(
        f"REVOKE UPDATE (allow_engagement_ranking) ON public.guilds FROM {SEAT_FLOOR}"
    )
    for table, column in reversed(COLUMNS):
        op.drop_column(table, column, schema="public")
