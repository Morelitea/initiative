"""marketplace catalog tables

The two ``public`` tables behind the marketplace: one row per listing, one per
published version. Catalog metadata only — there is no ``guild_id`` column
anywhere here, by design, so the catalog cannot record who installed what.

Access shape:

* **read** by any session that has been routed — a platform tier browsing the
  marketplace, and a guild role resolving a listing at install time. Both reach
  it through their base role, so the grant goes to ``platform_base`` and
  ``app_guild_base`` and a single permissive SELECT policy covers them.
* **write** by the system engine only (boot seeding, and later the registry
  refresh job). The schema default-grants the base/login roles full DML on every
  new ``public`` table, so those are revoked back to SELECT here and no write
  policy exists — a user-routed session is refused twice over.
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260812_0164"
down_revision = "20260811_0163"
branch_labels = None
depends_on = None


def _platform(role: str) -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    op.create_table(
        "marketplace_listings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uid", sa.String(length=14), nullable=False),
        sa.Column("public_id", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("publisher", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("long_description", sa.Text(), nullable=True),
        sa.Column("avatar_url", sa.String(length=2000), nullable=False),
        sa.Column(
            "images",
            sa.dialects.postgresql.JSONB(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("latest_version_id", sa.Integer(), nullable=True),
        sa.Column("installs_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("available", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uid"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index(
        "ix_marketplace_listings_kind", "marketplace_listings", ["kind"], unique=False
    )

    op.create_table(
        "marketplace_listing_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column(
            "definition",
            sa.dialects.postgresql.JSONB(),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("release_notes", sa.Text(), nullable=True),
        sa.Column("min_app_version", sa.String(length=32), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["listing_id"], ["marketplace_listings.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("listing_id", "version"),
    )
    op.create_index(
        "ix_marketplace_listing_versions_listing_id",
        "marketplace_listing_versions",
        ["listing_id"],
        unique=False,
    )
    # Added after both tables exist — the pointer closes a cycle between them.
    op.create_foreign_key(
        "fk_marketplace_listings_latest_version",
        "marketplace_listings",
        "marketplace_listing_versions",
        ["latest_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    base = _platform("base")
    for table in ("marketplace_listings", "marketplace_listing_versions"):
        _run(
            [
                f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY",
                f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY",
                # Wind the schema's default grants back to reads. The catalog is
                # public-to-any-session data, but only the system engine writes it.
                f"REVOKE ALL ON TABLE public.{table} "
                f'FROM app_guild_base, "{base}", app_user',
                f'GRANT SELECT ON TABLE public.{table} TO app_guild_base, "{base}"',
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
                f"public.{table} TO app_admin",
                # The system engine inserts, so it needs the id sequence; no
                # user-facing role ever does.
                f"REVOKE ALL ON SEQUENCE public.{table}_id_seq "
                f'FROM app_guild_base, "{base}", app_user',
                f"GRANT USAGE, SELECT ON SEQUENCE public.{table}_id_seq TO app_admin",
                f"DROP POLICY IF EXISTS {table}_read ON public.{table}",
                # One read policy, no write policy: a routed session can browse
                # the catalog and resolve a listing, and can never author one.
                f"CREATE POLICY {table}_read ON public.{table} "
                "AS PERMISSIVE FOR SELECT "
                f'TO app_guild_base, "{base}" USING (true)',
            ]
        )


def downgrade() -> None:
    for table in ("marketplace_listing_versions", "marketplace_listings"):
        _run(
            [
                f"DROP POLICY IF EXISTS {table}_read ON public.{table}",
                f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY",
            ]
        )
    op.drop_constraint(
        "fk_marketplace_listings_latest_version",
        "marketplace_listings",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_marketplace_listing_versions_listing_id",
        table_name="marketplace_listing_versions",
    )
    op.drop_table("marketplace_listing_versions")
    op.drop_index("ix_marketplace_listings_kind", table_name="marketplace_listings")
    op.drop_table("marketplace_listings")
