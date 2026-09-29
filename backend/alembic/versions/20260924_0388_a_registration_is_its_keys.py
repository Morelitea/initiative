"""a registration is its keys

A registration holds no secret and records no handshake. An app proves itself
with a JWT signed by a key its registration publishes, and Initiative signs
what it sends an app with the app platform's own key, so nothing is shared
between the two and nothing is fetched to fill a registration in.

- ``app_service_registrations.jwks_uri`` is added: where the app publishes its
  key set, on its base URL's own origin, as an alternative to the pasted
  ``jwks``.
- ``secret_encrypted``, ``status``, ``last_verified_at``, ``manifest_hash`` and
  ``protocol_version`` are dropped. Whether a registration is live is now
  ``enabled``, its publisher's ``enabled``, and a key set, computed where it is
  read.
- ``public.app_service_nonces``, the replay guard of the request-signing
  channel, is dropped with the channel.
- The install floor, ``app_install_base``, reads ``jwks`` and ``jwks_uri``:
  the install standing asks whether its registration has a key set. Column
  grants, beside the ones revisions 0379 and 0387 gave it.

Revision ID: 20260924_0388
Revises: 20260924_0387
Create Date: 2026-09-24
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260924_0388"
down_revision = "20260924_0387"
branch_labels = None
depends_on = None

REGISTRATIONS = "app_service_registrations"
NONCES = "app_service_nonces"


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def upgrade() -> None:
    op.add_column(
        REGISTRATIONS, sa.Column("jwks_uri", sa.String(length=1000), nullable=True)
    )
    for column in (
        "secret_encrypted",
        "status",
        "last_verified_at",
        "manifest_hash",
        "protocol_version",
    ):
        op.drop_column(REGISTRATIONS, column)

    op.drop_index(f"ix_{NONCES}_expires_at", table_name=NONCES)
    op.drop_table(NONCES)

    op.execute(
        f"GRANT SELECT (jwks, jwks_uri) ON public.{REGISTRATIONS} TO app_install_base"
    )


def downgrade() -> None:
    op.execute(
        f"REVOKE SELECT (jwks, jwks_uri) ON public.{REGISTRATIONS} "
        "FROM app_install_base"
    )

    op.create_table(
        NONCES,
        sa.Column("registration_id", sa.Integer(), nullable=False),
        sa.Column("nonce", sa.String(length=64), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["registration_id"],
            [f"{REGISTRATIONS}.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("registration_id", "nonce"),
    )
    op.create_index(f"ix_{NONCES}_expires_at", NONCES, ["expires_at"], unique=False)
    base = _platform_base()
    for statement in (
        f"ALTER TABLE public.{NONCES} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE public.{NONCES} FORCE ROW LEVEL SECURITY",
        f'REVOKE ALL ON TABLE public.{NONCES} FROM app_guild_base, "{base}", app_user',
        f"GRANT SELECT, INSERT, DELETE ON TABLE public.{NONCES} TO app_admin",
    ):
        op.execute(statement)

    op.add_column(
        REGISTRATIONS, sa.Column("secret_encrypted", sa.Text(), nullable=True)
    )
    op.add_column(
        REGISTRATIONS,
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="unverified",
            nullable=False,
        ),
    )
    op.add_column(
        REGISTRATIONS,
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        REGISTRATIONS, sa.Column("manifest_hash", sa.String(length=64), nullable=True)
    )
    op.add_column(
        REGISTRATIONS, sa.Column("protocol_version", sa.Integer(), nullable=True)
    )
    op.drop_column(REGISTRATIONS, "jwks_uri")
