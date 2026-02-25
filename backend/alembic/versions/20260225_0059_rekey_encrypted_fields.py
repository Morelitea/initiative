"""Re-encrypt 0058 fields with per-field derived keys.

Migration 0058 encrypted ai_api_key, oidc_client_secret, and smtp_password
using a single HKDF key derived from the salt b"oidc-refresh-token".
This migration decrypts each value with that old key and re-encrypts it
with a field-specific key so each secret type has cryptographic isolation.

Affected columns:
- app_settings.oidc_client_secret_encrypted  (new salt: b"oidc-client-secret")
- app_settings.smtp_password_encrypted        (new salt: b"smtp-password")
- app_settings.ai_api_key_encrypted           (new salt: b"ai-api-key")
- guild_settings.ai_api_key_encrypted         (new salt: b"ai-api-key")
- users.ai_api_key_encrypted                  (new salt: b"ai-api-key")

The oidc_refresh_token_encrypted column on users is NOT touched — it was
encrypted before 0058 and continues to use b"oidc-refresh-token".

Revision ID: 20260225_0059
Revises: 20260225_0058
Create Date: 2026-02-25
"""

from alembic import op
from sqlalchemy import text

revision = "20260225_0059"
down_revision = "20260225_0058"
branch_labels = None
depends_on = None


def _rekey_column(
    conn,
    table: str,
    column: str,
    old_salt: bytes,
    new_salt: bytes,
) -> None:
    from app.core.encryption import decrypt_field, encrypt_field

    rows = conn.execute(
        text(f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL")
    ).fetchall()
    for row_id, ciphertext in rows:
        if ciphertext:
            plaintext = decrypt_field(ciphertext, old_salt)
            new_ciphertext = encrypt_field(plaintext, new_salt)
            conn.execute(
                text(f"UPDATE {table} SET {column} = :ct WHERE id = :id"),
                {"ct": new_ciphertext, "id": row_id},
            )


def upgrade() -> None:
    from app.core.encryption import (
        SALT_AI_API_KEY,
        SALT_OIDC_CLIENT_SECRET,
        SALT_OIDC_REFRESH_TOKEN,
        SALT_SMTP_PASSWORD,
    )

    conn = op.get_bind()

    _rekey_column(conn, "app_settings", "oidc_client_secret_encrypted", SALT_OIDC_REFRESH_TOKEN, SALT_OIDC_CLIENT_SECRET)
    _rekey_column(conn, "app_settings", "smtp_password_encrypted",       SALT_OIDC_REFRESH_TOKEN, SALT_SMTP_PASSWORD)
    _rekey_column(conn, "app_settings", "ai_api_key_encrypted",          SALT_OIDC_REFRESH_TOKEN, SALT_AI_API_KEY)
    _rekey_column(conn, "guild_settings", "ai_api_key_encrypted",        SALT_OIDC_REFRESH_TOKEN, SALT_AI_API_KEY)
    _rekey_column(conn, "users",          "ai_api_key_encrypted",        SALT_OIDC_REFRESH_TOKEN, SALT_AI_API_KEY)


def downgrade() -> None:
    from app.core.encryption import (
        SALT_AI_API_KEY,
        SALT_OIDC_CLIENT_SECRET,
        SALT_OIDC_REFRESH_TOKEN,
        SALT_SMTP_PASSWORD,
    )

    conn = op.get_bind()

    # Reverse: re-encrypt with the old shared salt
    _rekey_column(conn, "users",          "ai_api_key_encrypted",        SALT_AI_API_KEY,         SALT_OIDC_REFRESH_TOKEN)
    _rekey_column(conn, "guild_settings", "ai_api_key_encrypted",        SALT_AI_API_KEY,         SALT_OIDC_REFRESH_TOKEN)
    _rekey_column(conn, "app_settings",   "ai_api_key_encrypted",        SALT_AI_API_KEY,         SALT_OIDC_REFRESH_TOKEN)
    _rekey_column(conn, "app_settings",   "smtp_password_encrypted",     SALT_SMTP_PASSWORD,      SALT_OIDC_REFRESH_TOKEN)
    _rekey_column(conn, "app_settings",   "oidc_client_secret_encrypted", SALT_OIDC_CLIENT_SECRET, SALT_OIDC_REFRESH_TOKEN)
