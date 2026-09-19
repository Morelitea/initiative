"""An initiative membership records which provider manages it.

The guild-side half of ``20260915_0270``. ``oidc_managed`` said that group sync
made the row; ``oidc_provider_id`` says which provider's sync did, so a sign-in
through one provider reclaims only what that provider granted.

A plain integer and no foreign key: this table lives in a guild schema and
``auth_providers`` lives in ``public``, which is the arrangement every other
reference across that line uses. It carries no RLS — the structural initiative
tables are guild-level, guarded by the schema boundary — so the backfill needs
no FORCE lifted.

Edited after it shipped in 0.70.0, for the same reason as 0270: the provider
it attributes to is read from ``public.auth_providers``, which FORCEs RLS and
admits nothing to the owner a migration runs as. A database with a managed
membership therefore stopped with "nothing to attribute them to". Nothing that
passed the released version had such a row, so this one leaves it as it was.
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260915_0271"
down_revision = "20260915_0270"
branch_labels = None
depends_on = None

PLATFORM_SLUG = "oidc"


def _platform_provider_id(bind) -> int | None:
    # Read once, with FORCE lifted for the length of the read, since the table
    # has no policy a migration's empty request context could match.
    op.execute("ALTER TABLE public.auth_providers NO FORCE ROW LEVEL SECURITY")
    try:
        return bind.execute(
            sa.text(
                "SELECT id FROM public.auth_providers "
                "WHERE slug = :slug AND guild_id IS NULL"
            ),
            {"slug": PLATFORM_SLUG},
        ).scalar()
    finally:
        op.execute("ALTER TABLE public.auth_providers FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    bind = op.get_bind()
    platform_id = _platform_provider_id(bind)
    run_for_each_guild_schema(bind, lambda: _apply_upgrade(platform_id))


def _apply_upgrade(platform_id: int | None) -> None:
    bind = op.get_bind()
    op.add_column(
        "initiative_members", sa.Column("oidc_provider_id", sa.Integer(), nullable=True)
    )
    op.create_index(
        "ix_initiative_members_oidc_provider_id",
        "initiative_members",
        ["oidc_provider_id"],
    )

    managed = bind.execute(
        sa.text("SELECT count(*) FROM initiative_members WHERE oidc_managed")
    ).scalar()
    if managed:
        if platform_id is None:
            raise RuntimeError(
                "initiative_members carries OIDC-managed rows but no "
                f"auth_providers row has slug {PLATFORM_SLUG!r} with guild_id "
                "NULL, so there is nothing to attribute them to"
            )
        moved = bind.execute(
            sa.text(
                "UPDATE initiative_members SET oidc_provider_id = :pid "
                "WHERE oidc_managed"
            ),
            {"pid": platform_id},
        ).rowcount
        assert moved == managed, f"attributed {moved} of {managed} memberships"

    op.drop_column("initiative_members", "oidc_managed")


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    op.add_column(
        "initiative_members",
        sa.Column(
            "oidc_managed",
            sa.BOOLEAN(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE initiative_members SET oidc_managed = true "
        "WHERE oidc_provider_id IS NOT NULL"
    )
    op.drop_index("ix_initiative_members_oidc_provider_id", "initiative_members")
    op.drop_column("initiative_members", "oidc_provider_id")
