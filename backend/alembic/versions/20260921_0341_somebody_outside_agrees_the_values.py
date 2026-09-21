"""Somebody outside the community agrees which values are its own.

A community names the claim values that make an arrival one of its people,
and nothing in the application can tell whether it holds the domain or tenant
they describe. The answer becomes a column: support records it through the
case raised when the values are written, or the operator does on the
community's own page where a deployment runs no intake.

What waits for it is ``auto_join``. A connection still decides who may use its
button the moment it is saved.

Existing connections are recorded as agreed: they were written under the rule
as it stood and are in use, and an upgrade should ask nothing of a deployment
it was not already asking. The column applies from here — writing different
values clears it, which is what the application does.

``guild_provider_connections`` forces RLS on its owner, which is the role this
runs as, so the write lifts it and puts it back.

Revision ID: 20260921_0341
Revises: 20260921_0340
Create Date: 2026-09-21
"""

from alembic import op
import sqlalchemy as sa

revision = "20260921_0341"
down_revision = "20260921_0340"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "guild_provider_connections",
        sa.Column("narrowing_approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "guild_provider_connections",
        sa.Column("narrowing_approved_by", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_guild_provider_connections_narrowing_approved_by",
        "guild_provider_connections",
        "users",
        ["narrowing_approved_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute("ALTER TABLE guild_provider_connections NO FORCE ROW LEVEL SECURITY")
    try:
        carried = (
            op.get_bind()
            .execute(
                sa.text(
                    "UPDATE guild_provider_connections "
                    "SET narrowing_approved_at = now() "
                    "WHERE claim IS NOT NULL"
                )
            )
            .rowcount
        )
        print(f"narrowing_approved_at: {carried} connection(s) carried over")
    finally:
        op.execute("ALTER TABLE guild_provider_connections FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_constraint(
        "fk_guild_provider_connections_narrowing_approved_by",
        "guild_provider_connections",
        type_="foreignkey",
    )
    op.drop_column("guild_provider_connections", "narrowing_approved_by")
    op.drop_column("guild_provider_connections", "narrowing_approved_at")
