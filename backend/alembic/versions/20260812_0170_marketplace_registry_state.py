"""marketplace registry client state

Two ``public`` tables behind the signed-registry client.

``marketplace_registry_state`` records what this deployment last accepted from
one registry — the serial, the index digest, and when. It is persisted rather
than kept in memory because it is what makes an older index detectable as
older: state that resets on restart would accept a replayed index on every
boot, and each replica would answer differently.

``marketplace_media`` holds the artwork a verified index named, mirrored here
and addressed by the SHA-256 of its own bytes, so a stored listing's images are
served from this deployment.

Access shape:

* ``marketplace_registry_state`` — system engine only. The request path holds
  no grant and the table carries no policy, so operator bookkeeping is reached
  through a capability-gated endpoint rather than by any routed session.
* ``marketplace_media`` — read by anyone holding the digest, including before a
  session is routed: these bytes stand in for the static image files the build
  ships, which are served the same way. Written by the system engine alone.

Both tables get the schema's default grants wound back explicitly first — every
new ``public`` table is created writable by the routed base roles.
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260812_0170"
down_revision = "20260812_0169"
branch_labels = None
depends_on = None


def _platform(role: str) -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    op.create_table(
        "marketplace_registry_state",
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

    op.create_table(
        "marketplace_media",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sha256"),
    )

    base = _platform("base")

    # --- registry state: system engine only --------------------------------
    _run(
        [
            "ALTER TABLE public.marketplace_registry_state ENABLE ROW LEVEL SECURITY",
            "ALTER TABLE public.marketplace_registry_state FORCE ROW LEVEL SECURITY",
            "REVOKE ALL ON TABLE public.marketplace_registry_state "
            f'FROM app_guild_base, "{base}", app_user',
            "GRANT SELECT, INSERT, UPDATE ON TABLE "
            "public.marketplace_registry_state TO app_admin",
            "REVOKE ALL ON SEQUENCE public.marketplace_registry_state_id_seq "
            f'FROM app_guild_base, "{base}", app_user',
            "GRANT USAGE, SELECT ON SEQUENCE "
            "public.marketplace_registry_state_id_seq TO app_admin",
            # No policy at all: RLS is enabled and forced, so even a role that
            # somehow held a grant would select nothing.
            "DROP POLICY IF EXISTS marketplace_registry_state_read "
            "ON public.marketplace_registry_state",
        ]
    )

    # --- mirrored artwork: readable, written by the system engine ----------
    _run(
        [
            "ALTER TABLE public.marketplace_media ENABLE ROW LEVEL SECURITY",
            "ALTER TABLE public.marketplace_media FORCE ROW LEVEL SECURITY",
            "REVOKE ALL ON TABLE public.marketplace_media "
            f'FROM app_guild_base, "{base}", app_user',
            "GRANT SELECT ON TABLE public.marketplace_media "
            f'TO app_guild_base, "{base}", app_user',
            "GRANT SELECT, INSERT, DELETE ON TABLE "
            "public.marketplace_media TO app_admin",
            "REVOKE ALL ON SEQUENCE public.marketplace_media_id_seq "
            f'FROM app_guild_base, "{base}", app_user',
            "GRANT USAGE, SELECT ON SEQUENCE "
            "public.marketplace_media_id_seq TO app_admin",
            "DROP POLICY IF EXISTS marketplace_media_read ON public.marketplace_media",
            # A read policy and no write policy, matching the catalog tables:
            # artwork is public the way the shipped image files are, and the
            # only writer is the system engine.
            "CREATE POLICY marketplace_media_read ON public.marketplace_media "
            "AS PERMISSIVE FOR SELECT "
            f'TO app_guild_base, "{base}", app_user USING (true)',
        ]
    )


def downgrade() -> None:
    _run(
        [
            "DROP POLICY IF EXISTS marketplace_media_read ON public.marketplace_media",
            "ALTER TABLE public.marketplace_media DISABLE ROW LEVEL SECURITY",
            "ALTER TABLE public.marketplace_registry_state DISABLE ROW LEVEL SECURITY",
        ]
    )
    op.drop_table("marketplace_media")
    op.drop_table("marketplace_registry_state")
