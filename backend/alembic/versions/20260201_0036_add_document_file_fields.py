"""Add file document support fields

Revision ID: 20260201_0036
Revises: 20260201_0035
Create Date: 2026-02-01

Adds document_type enum and file-related columns to support uploading
file documents (PDF, DOCX, etc.) alongside native Lexical documents.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260201_0036"
down_revision = "20260201_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the document_type enum
    document_type_enum = sa.Enum("native", "file", name="document_type")
    document_type_enum.create(op.get_bind(), checkfirst=True)

    # Add columns to documents table
    op.add_column(
        "documents",
        sa.Column(
            "document_type",
            sa.Enum("native", "file", name="document_type"),
            nullable=False,
            server_default=sa.text("'native'"),
        ),
    )
    op.add_column(
        "documents",
        sa.Column("file_url", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("file_content_type", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("file_size", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("original_filename", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    # Drop columns
    op.drop_column("documents", "original_filename")
    op.drop_column("documents", "file_size")
    op.drop_column("documents", "file_content_type")
    op.drop_column("documents", "file_url")
    op.drop_column("documents", "document_type")

    # Drop the enum type
    sa.Enum(name="document_type").drop(op.get_bind(), checkfirst=True)
