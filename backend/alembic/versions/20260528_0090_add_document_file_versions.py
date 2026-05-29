"""Add document_file_versions table for file-document version history.

Each uploaded version of a file-type document gets a row here. The
``documents`` row mirrors the file fields of the current version (the highest
``version_number``), so the existing download endpoint and viewer keep working
without consulting this table. Backfills a version-1 row for every existing
file document.

Revision ID: 20260528_0090
Revises: 20260524_0089
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa

revision = "20260528_0090"
down_revision = "20260524_0089"
branch_labels = None
depends_on = None

IS_SUPER = "current_setting('app.is_superadmin', true) = 'true'"


def upgrade() -> None:
    op.create_table(
        "document_file_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("file_url", sa.String(length=512), nullable=False),
        sa.Column("file_content_type", sa.String(length=128), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("uploaded_by_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        # uploaded_by_id uses the default RESTRICT (like documents.created_by_id /
        # updated_by_id): version history must outlive the uploader. hard_delete_user
        # reassigns these rows to the system user via reassign_user_content() first.
        sa.ForeignKeyConstraint(["uploaded_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "version_number", name="uq_dfv_document_version"),
    )
    op.create_index(
        "ix_document_file_versions_document_id",
        "document_file_versions",
        ["document_id"],
    )

    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE document_file_versions ENABLE ROW LEVEL SECURITY"))
    conn.execute(sa.text("ALTER TABLE document_file_versions FORCE ROW LEVEL SECURITY"))
    conn.execute(sa.text(f"""
        CREATE POLICY guild_isolation ON document_file_versions
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

    # Backfill a version-1 row for every existing file document (including
    # soft-deleted ones — they still own their blob and may be restored).
    conn.execute(sa.text("""
        INSERT INTO document_file_versions
            (document_id, guild_id, version_number, file_url, file_content_type,
             file_size, original_filename, uploaded_by_id, created_at)
        SELECT id, guild_id, 1, file_url, file_content_type,
               file_size, original_filename, created_by_id, created_at
        FROM documents
        WHERE document_type = 'file' AND file_url IS NOT NULL
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP POLICY IF EXISTS guild_isolation ON document_file_versions"))
    conn.execute(sa.text("ALTER TABLE document_file_versions DISABLE ROW LEVEL SECURITY"))
    op.drop_index("ix_document_file_versions_document_id", table_name="document_file_versions")
    op.drop_table("document_file_versions")
