"""Hash user_tokens at rest and cap absurd device-token expiries.

SEC-13: device (and email/reset) tokens were stored as plaintext in
``user_tokens.token`` and device tokens were minted with a ~100-year TTL
(36500 days). Both are now hardened in the service layer:

* ``token`` stores ``sha256(raw_token)`` (hex), mirroring ``user_api_keys``;
  lookups hash the presented value before comparing.
* device tokens use a sliding 90-day window (refreshed on use).

This migration brings existing rows in line so currently-logged-in devices and
in-flight verification/reset links keep working:

1. Hash every existing plaintext ``token`` in place. SHA-256 is deterministic,
   so the same lookup the service now performs (``sha256(presented_token)``)
   matches the migrated row. PostgreSQL 11+'s built-in ``sha256(bytea)`` is used —
   no ``pgcrypto`` extension required.
2. Cap any device-token ``expires_at`` that exceeds now + 90 days down to that
   cap, so the legacy ~100-year tokens expire within the new window.

The hash is one-way, so ``downgrade`` cannot restore plaintext; it is a no-op
documented below. Roll-forward only.

Revision ID: 20260611_0101
Revises: 20260609_0100
Create Date: 2026-06-11
"""

from alembic import op

revision = "20260611_0101"
down_revision = "20260609_0100"
branch_labels = None
depends_on = None

# A SHA-256 hex digest is always 64 chars, so a token that is exactly 64
# lowercase-hex characters is treated as already hashed and skipped. Raw tokens
# are ``secrets.token_urlsafe(48)`` (~64 url-safe chars, mixed case / -, _), so
# this guard is a safety net for re-runs, not a precise discriminator.
_ALREADY_HASHED = "token ~ '^[0-9a-f]{64}$'"


def upgrade() -> None:
    # 1. Hash existing plaintext tokens in place (idempotent: skip rows that
    #    already look like a SHA-256 hex digest so re-running is safe).
    op.execute(
        f"""
        UPDATE user_tokens
        SET token = encode(sha256(token::bytea), 'hex')
        WHERE NOT ({_ALREADY_HASHED})
        """
    )

    # 2. Cap any device-token expiry that runs past the new 90-day window
    #    (the legacy 36500-day tokens) down to now + 90 days.
    op.execute(
        """
        UPDATE user_tokens
        SET expires_at = (now() AT TIME ZONE 'utc') + interval '90 days'
        WHERE purpose = 'device_auth'
          AND expires_at > (now() AT TIME ZONE 'utc') + interval '90 days'
        """
    )


def downgrade() -> None:
    # SHA-256 is one-way: the original plaintext tokens cannot be recovered, and
    # the capped expiries are not tracked. There is nothing to reverse — leaving
    # the hashed values and capped expiries in place is the only safe behavior.
    pass
