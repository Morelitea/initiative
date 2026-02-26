"""Add uploads table for guild-scoped file tracking.

Revision ID: 20260225_0060
Revises: 20260225_0059
Create Date: 2026-02-25
"""

from alembic import op
import sqlalchemy as sa

revision = "20260225_0060"
down_revision = "20260225_0059"
branch_labels = None
depends_on = None

IS_SUPER = "current_setting('app.is_superadmin', true) = 'true'"


def upgrade() -> None:
    op.create_table(
        "uploads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("uploader_user_id", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploader_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_uploads_filename", "uploads", ["filename"], unique=True)
    op.create_index("ix_uploads_guild_id", "uploads", ["guild_id"])

    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE uploads ENABLE ROW LEVEL SECURITY"))
    conn.execute(sa.text("ALTER TABLE uploads FORCE ROW LEVEL SECURITY"))
    conn.execute(sa.text(f"""
        CREATE POLICY guild_isolation ON uploads
        FOR ALL
        USING (
            guild_id = current_setting('app.current_guild_id', true)::int
            OR {IS_SUPER}
        )
        WITH CHECK (
            guild_id = current_setting('app.current_guild_id', true)::int
            OR {IS_SUPER}
        )
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP POLICY IF EXISTS guild_isolation ON uploads"))
    conn.execute(sa.text("ALTER TABLE uploads DISABLE ROW LEVEL SECURITY"))
    op.drop_index("ix_uploads_guild_id", table_name="uploads")
    op.drop_index("ix_uploads_filename", table_name="uploads")
    op.drop_table("uploads")
