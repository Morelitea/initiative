"""Encrypt sensitive database fields at rest.

Renames plaintext columns to *_encrypted and migrates existing data
through Fernet encryption.  Affected columns:

- app_settings.oidc_client_secret      -> oidc_client_secret_encrypted
- app_settings.smtp_password            -> smtp_password_encrypted  (size 255 -> 2000)
- app_settings.ai_api_key              -> ai_api_key_encrypted
- guild_settings.ai_api_key            -> ai_api_key_encrypted
- users.ai_api_key                     -> ai_api_key_encrypted

Revision ID: 20260225_0058
Revises: 20260223_0057
Create Date: 2026-02-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "20260225_0058"
down_revision = "20260223_0057"
branch_labels = None
depends_on = None


def _encrypt_column(
    conn: sa.engine.Connection,
    table: str,
    old_col: str,
    new_col: str,
) -> None:
    """Read plaintext values, encrypt them, and write to the new column."""
    from app.core.encryption import encrypt_token

    rows = conn.execute(
        text(f"SELECT id, {old_col} FROM {table} WHERE {old_col} IS NOT NULL")
    ).fetchall()
    for row_id, plaintext in rows:
        if plaintext:
            ciphertext = encrypt_token(plaintext)
            conn.execute(
                text(f"UPDATE {table} SET {new_col} = :ct WHERE id = :id"),
                {"ct": ciphertext, "id": row_id},
            )


def _decrypt_column(
    conn: sa.engine.Connection,
    table: str,
    encrypted_col: str,
    plain_col: str,
) -> None:
    """Read encrypted values, decrypt them, and write to the plaintext column."""
    from app.core.encryption import decrypt_token

    rows = conn.execute(
        text(f"SELECT id, {encrypted_col} FROM {table} WHERE {encrypted_col} IS NOT NULL")
    ).fetchall()
    for row_id, ciphertext in rows:
        if ciphertext:
            plaintext = decrypt_token(ciphertext)
            conn.execute(
                text(f"UPDATE {table} SET {plain_col} = :pt WHERE id = :id"),
                {"pt": plaintext, "id": row_id},
            )


def upgrade() -> None:
    conn = op.get_bind()

    # --- app_settings ---

    # oidc_client_secret -> oidc_client_secret_encrypted
    op.add_column(
        "app_settings",
        sa.Column("oidc_client_secret_encrypted", sa.String(), nullable=True),
    )
    _encrypt_column(conn, "app_settings", "oidc_client_secret", "oidc_client_secret_encrypted")
    op.drop_column("app_settings", "oidc_client_secret")

    # smtp_password -> smtp_password_encrypted  (increase size to 2000)
    op.add_column(
        "app_settings",
        sa.Column("smtp_password_encrypted", sa.String(2000), nullable=True),
    )
    _encrypt_column(conn, "app_settings", "smtp_password", "smtp_password_encrypted")
    op.drop_column("app_settings", "smtp_password")

    # ai_api_key -> ai_api_key_encrypted
    op.add_column(
        "app_settings",
        sa.Column("ai_api_key_encrypted", sa.String(2000), nullable=True),
    )
    _encrypt_column(conn, "app_settings", "ai_api_key", "ai_api_key_encrypted")
    op.drop_column("app_settings", "ai_api_key")

    # --- guild_settings ---

    # ai_api_key -> ai_api_key_encrypted
    op.add_column(
        "guild_settings",
        sa.Column("ai_api_key_encrypted", sa.String(2000), nullable=True),
    )
    _encrypt_column(conn, "guild_settings", "ai_api_key", "ai_api_key_encrypted")
    op.drop_column("guild_settings", "ai_api_key")

    # --- users ---

    # ai_api_key -> ai_api_key_encrypted
    op.add_column(
        "users",
        sa.Column("ai_api_key_encrypted", sa.String(2000), nullable=True),
    )
    _encrypt_column(conn, "users", "ai_api_key", "ai_api_key_encrypted")
    op.drop_column("users", "ai_api_key")


def downgrade() -> None:
    conn = op.get_bind()

    # --- users ---
    op.add_column(
        "users",
        sa.Column("ai_api_key", sa.String(2000), nullable=True),
    )
    _decrypt_column(conn, "users", "ai_api_key_encrypted", "ai_api_key")
    op.drop_column("users", "ai_api_key_encrypted")

    # --- guild_settings ---
    op.add_column(
        "guild_settings",
        sa.Column("ai_api_key", sa.String(2000), nullable=True),
    )
    _decrypt_column(conn, "guild_settings", "ai_api_key_encrypted", "ai_api_key")
    op.drop_column("guild_settings", "ai_api_key_encrypted")

    # --- app_settings ---
    op.add_column(
        "app_settings",
        sa.Column("ai_api_key", sa.String(2000), nullable=True),
    )
    _decrypt_column(conn, "app_settings", "ai_api_key_encrypted", "ai_api_key")
    op.drop_column("app_settings", "ai_api_key_encrypted")

    op.add_column(
        "app_settings",
        sa.Column("smtp_password", sa.String(255), nullable=True),
    )
    _decrypt_column(conn, "app_settings", "smtp_password_encrypted", "smtp_password")
    op.drop_column("app_settings", "smtp_password_encrypted")

    op.add_column(
        "app_settings",
        sa.Column("oidc_client_secret", sa.String(), nullable=True),
    )
    _decrypt_column(conn, "app_settings", "oidc_client_secret_encrypted", "oidc_client_secret")
    op.drop_column("app_settings", "oidc_client_secret_encrypted")
