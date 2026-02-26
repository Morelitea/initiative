"""Encrypt email addresses at rest.

Adds email_hash (HMAC-SHA256, used for lookups) and email_encrypted (Fernet)
to the users table, backfills existing rows, drops the plaintext email column,
and adds the same invitee_email_encrypted column to guild_invites.

Revision ID: 20260225_0059
Revises: 20260225_0058
Create Date: 2026-02-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "20260225_0059"
down_revision = "20260225_0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.core.encryption import encrypt_field, decrypt_field, hash_email, SALT_EMAIL

    conn = op.get_bind()

    # ── users ────────────────────────────────────────────────────────────────

    # 1. Add new nullable columns
    op.add_column("users", sa.Column("email_hash", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("email_encrypted", sa.String(2000), nullable=True))

    # 2. Backfill
    rows = conn.execute(text("SELECT id, email FROM users WHERE email IS NOT NULL")).fetchall()
    for row_id, plaintext_email in rows:
        if plaintext_email:
            normalized = plaintext_email.lower().strip()
            conn.execute(
                text("UPDATE users SET email_hash = :h, email_encrypted = :e WHERE id = :id"),
                {
                    "h": hash_email(normalized),
                    "e": encrypt_field(normalized, SALT_EMAIL),
                    "id": row_id,
                },
            )

    # 3. Add unique constraint and make NOT NULL
    op.alter_column("users", "email_hash", nullable=False)
    op.alter_column("users", "email_encrypted", nullable=False)
    op.create_unique_constraint("uq_users_email_hash", "users", ["email_hash"])

    # 4. Drop the old plaintext column (unique constraint drops with it)
    op.drop_column("users", "email")

    # ── guild_invites ─────────────────────────────────────────────────────────

    # 5. Add encrypted column
    op.add_column("guild_invites", sa.Column("invitee_email_encrypted", sa.String(2000), nullable=True))

    # 6. Backfill
    rows = conn.execute(text("SELECT id, invitee_email FROM guild_invites WHERE invitee_email IS NOT NULL")).fetchall()
    for row_id, plaintext_email in rows:
        if plaintext_email:
            conn.execute(
                text("UPDATE guild_invites SET invitee_email_encrypted = :e WHERE id = :id"),
                {"e": encrypt_field(plaintext_email.lower().strip(), SALT_EMAIL), "id": row_id},
            )

    # 7. Drop old column
    op.drop_column("guild_invites", "invitee_email")


def downgrade() -> None:
    from app.core.encryption import decrypt_field, SALT_EMAIL

    conn = op.get_bind()

    # ── guild_invites ─────────────────────────────────────────────────────────

    op.add_column("guild_invites", sa.Column("invitee_email", sa.String(), nullable=True))

    rows = conn.execute(
        text("SELECT id, invitee_email_encrypted FROM guild_invites WHERE invitee_email_encrypted IS NOT NULL")
    ).fetchall()
    for row_id, ciphertext in rows:
        if ciphertext:
            conn.execute(
                text("UPDATE guild_invites SET invitee_email = :pt WHERE id = :id"),
                {"pt": decrypt_field(ciphertext, SALT_EMAIL), "id": row_id},
            )

    op.drop_column("guild_invites", "invitee_email_encrypted")

    # ── users ────────────────────────────────────────────────────────────────

    op.add_column("users", sa.Column("email", sa.String(), nullable=True))

    rows = conn.execute(
        text("SELECT id, email_encrypted FROM users WHERE email_encrypted IS NOT NULL")
    ).fetchall()
    for row_id, ciphertext in rows:
        if ciphertext:
            conn.execute(
                text("UPDATE users SET email = :pt WHERE id = :id"),
                {"pt": decrypt_field(ciphertext, SALT_EMAIL), "id": row_id},
            )

    op.drop_constraint("uq_users_email_hash", "users", type_="unique")
    op.drop_column("users", "email_hash")
    op.drop_column("users", "email_encrypted")

    # Restore unique constraint on email
    op.alter_column("users", "email", nullable=False)
    op.create_unique_constraint("uq_users_email", "users", ["email"])
