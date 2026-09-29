"""the registry is a TUF repository

The marketplace registry is read with a TUF client, trusting a root that ships
in the image, and it brings publishers and app registrations as well as
listings.

- ``public.marketplace_tuf_metadata``: the TUF metadata this deployment last
  verified, one row per role (and per root version). System engine only.
- ``public.marketplace_registry_status``: one row, how the last refresh went.
  System engine only.
- ``public.marketplace_registry_state``, the detached-signature client's
  bookkeeping, is dropped with that client.
- ``publishers.source``: ``seed``, ``operator`` or ``registry``. The row boot
  seeds for this project's own prefix is ``seed``; every other existing row
  was added by an operator.
- ``marketplace_listings.publisher_id`` and ``publisher_verified``: the
  publisher record a registry listing arrived under.
- ``app_service_registrations``: ``source``, ``image_digest``,
  ``reference_sectors`` and ``root_is_builtin``, and ``base_url`` becomes
  nullable, since a registry container registration has no location until the
  operator gives one. Such a row is not live, and the install standing now
  reads ``base_url`` to say so: a column grant to ``app_install_base`` beside
  the ones revisions 0379, 0387 and 0388 gave it.
- ``app_settings.marketplace_registry_enabled``: the platform switch, on.

Revision ID: 20260924_0390
Revises: 20260924_0389
Create Date: 2026-09-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import settings

revision = "20260924_0390"
down_revision = "20260924_0389"
branch_labels = None
depends_on = None

METADATA = "marketplace_tuf_metadata"
STATUS = "marketplace_registry_status"
OLD_STATE = "marketplace_registry_state"
PUBLISHERS = "publishers"
LISTINGS = "marketplace_listings"
REGISTRATIONS = "app_service_registrations"
SETTINGS = "app_settings"

#: The prefix boot seeds this project's publisher under.
FIRST_PARTY_PREFIX = "morelitea"


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def _system_only(table: str, verbs: str) -> list[str]:
    base = _platform_base()
    return [
        f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY",
        f'REVOKE ALL ON TABLE public.{table} FROM app_user, app_guild_base, "{base}"',
        f"GRANT {verbs} ON TABLE public.{table} TO app_admin",
    ]


def upgrade() -> None:
    # --- the verified metadata and the status row: system engine only -----
    op.create_table(
        METADATA,
        sa.Column("role", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("role", "version"),
    )
    op.create_table(
        STATUS,
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("root_sha256", sa.String(length=64), nullable=True),
        sa.Column("root_version", sa.Integer(), nullable=True),
        sa.Column("snapshot_version", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=2000), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=64), nullable=True),
        sa.Column("listing_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="marketplace_registry_status_one_row"),
        sa.PrimaryKeyConstraint("id"),
    )
    _run(_system_only(METADATA, "SELECT, INSERT, UPDATE, DELETE"))
    _run(_system_only(STATUS, "SELECT, INSERT, UPDATE"))

    # --- the old client's bookkeeping --------------------------------------
    op.execute(f"ALTER TABLE public.{OLD_STATE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE public.{OLD_STATE} DISABLE ROW LEVEL SECURITY")
    op.drop_table(OLD_STATE)

    # --- publishers: where each row came from -------------------------------
    op.add_column(
        PUBLISHERS,
        sa.Column(
            "source", sa.String(length=16), server_default="operator", nullable=False
        ),
    )
    op.execute(f"ALTER TABLE public.{PUBLISHERS} NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(
            sa.text(
                f"UPDATE public.{PUBLISHERS} SET source = 'seed' WHERE prefix = :prefix"
            ).bindparams(prefix=FIRST_PARTY_PREFIX)
        )
    finally:
        op.execute(f"ALTER TABLE public.{PUBLISHERS} FORCE ROW LEVEL SECURITY")

    # --- listings: the publisher record a registry listing arrived under ----
    op.add_column(LISTINGS, sa.Column("publisher_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        f"{LISTINGS}_publisher_id_fkey",
        LISTINGS,
        PUBLISHERS,
        ["publisher_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(f"ix_{LISTINGS}_publisher_id", LISTINGS, ["publisher_id"])
    op.add_column(
        LISTINGS,
        sa.Column(
            "publisher_verified",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )

    # --- registrations: registry rows ---------------------------------------
    op.add_column(
        REGISTRATIONS,
        sa.Column(
            "source", sa.String(length=16), server_default="operator", nullable=False
        ),
    )
    op.add_column(
        REGISTRATIONS,
        sa.Column("image_digest", sa.String(length=500), nullable=True),
    )
    op.add_column(
        REGISTRATIONS,
        sa.Column(
            "reference_sectors",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.add_column(
        REGISTRATIONS,
        sa.Column(
            "root_is_builtin", sa.Boolean(), server_default="false", nullable=False
        ),
    )
    op.alter_column(
        REGISTRATIONS, "base_url", existing_type=sa.String(length=1000), nullable=True
    )
    op.execute(f"GRANT SELECT (base_url) ON public.{REGISTRATIONS} TO app_install_base")

    # --- the platform switch -------------------------------------------------
    op.add_column(
        SETTINGS,
        sa.Column(
            "marketplace_registry_enabled",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column(SETTINGS, "marketplace_registry_enabled")

    op.execute(
        f"REVOKE SELECT (base_url) ON public.{REGISTRATIONS} FROM app_install_base"
    )
    # The previous build requires a location on every registration, so a
    # registry container the operator never placed goes.
    op.execute(f"ALTER TABLE public.{REGISTRATIONS} NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(f"DELETE FROM public.{REGISTRATIONS} WHERE base_url IS NULL")
    finally:
        op.execute(f"ALTER TABLE public.{REGISTRATIONS} FORCE ROW LEVEL SECURITY")
    op.alter_column(
        REGISTRATIONS, "base_url", existing_type=sa.String(length=1000), nullable=False
    )
    for column in ("root_is_builtin", "reference_sectors", "image_digest", "source"):
        op.drop_column(REGISTRATIONS, column)

    op.drop_column(LISTINGS, "publisher_verified")
    op.drop_index(f"ix_{LISTINGS}_publisher_id", table_name=LISTINGS)
    op.drop_constraint(f"{LISTINGS}_publisher_id_fkey", LISTINGS, type_="foreignkey")
    op.drop_column(LISTINGS, "publisher_id")

    op.drop_column(PUBLISHERS, "source")

    op.create_table(
        OLD_STATE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("registry_url", sa.String(length=2000), nullable=False),
        sa.Column("key_id", sa.String(length=128), nullable=True),
        sa.Column("last_serial", sa.BigInteger(), nullable=True),
        sa.Column("last_index_sha256", sa.String(length=64), nullable=True),
        sa.Column("last_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=64), nullable=True),
        sa.Column("listing_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("registry_url"),
    )
    base = _platform_base()
    _run(
        _system_only(OLD_STATE, "SELECT, INSERT, UPDATE")
        + [
            f"REVOKE ALL ON SEQUENCE public.{OLD_STATE}_id_seq "
            f'FROM app_guild_base, "{base}", app_user',
            f"GRANT USAGE, SELECT ON SEQUENCE public.{OLD_STATE}_id_seq TO app_admin",
        ]
    )

    for table in (STATUS, METADATA):
        op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
        op.drop_table(table)
