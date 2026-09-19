"""A claim rule reads one provider, and a membership has one manager.

``oidc_claim_mappings`` matched on a claim value alone, and a membership
recorded only that OIDC made it. Two operator-global providers therefore read
each other's rules and reclaimed each other's memberships.

Both facts are recorded now. The backfill points everything at the provider
with the platform slug: every rule that exists was written against the claim
path the single settings form configured, and that form wrote this row.

Edited after it shipped in 0.70.0, which the freeze rule otherwise forbids.
As released, it read the three tables with FORCE ROW LEVEL SECURITY still on,
and the owner a migration runs as sees nothing through that: no provider, no
rules, no managed memberships. The backfill was skipped and ``SET NOT NULL``
then met the rows the count had not, so on every database that had a rule the
revision failed and was never stamped — those deployments are still at 0269
and will run this version. The databases that did pass it held no rule, and
this version leaves such a database exactly as the released one did.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260915_0270"
down_revision = "20260915_0269"
branch_labels = None
depends_on = None

PLATFORM_SLUG = "oidc"

# Every table this revision reads or writes rows of. Each FORCEs row-level
# security, which binds the owner the migration runs as, and their policies
# key on request GUCs a migration has no value for — read through FORCE, a
# table is empty whatever it holds. Lifted for the length of the revision and
# restored, as 0193 does for one table; the DDL is unaffected either way.
FORCED_TABLES = ("auth_providers", "oidc_claim_mappings", "guild_memberships")


def _lift_force() -> None:
    for table in FORCED_TABLES:
        op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")


def _restore_force() -> None:
    for table in FORCED_TABLES:
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _lift_force()
    try:
        _attribute_to_the_platform_provider()
    finally:
        _restore_force()


def _attribute_to_the_platform_provider() -> None:
    bind = op.get_bind()

    # Which provider the existing rows belong to. Read before anything is
    # added, so a deployment that has rules but no platform row stops here
    # rather than half-applying.
    platform_id = bind.execute(
        sa.text(
            "SELECT id FROM auth_providers WHERE slug = :slug AND guild_id IS NULL"
        ),
        {"slug": PLATFORM_SLUG},
    ).scalar()

    rules = bind.execute(sa.text("SELECT count(*) FROM oidc_claim_mappings")).scalar()
    managed = bind.execute(
        sa.text("SELECT count(*) FROM guild_memberships WHERE oidc_managed")
    ).scalar()
    if (rules or managed) and platform_id is None:
        raise RuntimeError(
            "oidc_claim_mappings/guild_memberships carry OIDC-managed rows but "
            f"no auth_providers row has slug {PLATFORM_SLUG!r} with guild_id "
            "NULL, so there is nothing to attribute them to"
        )

    # ── the rule's provider ────────────────────────────────────────────────
    op.add_column(
        "oidc_claim_mappings", sa.Column("provider_id", sa.Integer(), nullable=True)
    )
    if rules:
        moved = bind.execute(
            sa.text("UPDATE oidc_claim_mappings SET provider_id = :pid"),
            {"pid": platform_id},
        ).rowcount
        assert moved == rules, f"attributed {moved} of {rules} claim rules"
    op.alter_column("oidc_claim_mappings", "provider_id", nullable=False)
    op.create_index(
        "ix_oidc_claim_mappings_provider_id", "oidc_claim_mappings", ["provider_id"]
    )
    op.create_foreign_key(
        "fk_oidc_claim_mappings_provider",
        "oidc_claim_mappings",
        "auth_providers",
        ["provider_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ── the membership's manager ───────────────────────────────────────────
    op.add_column(
        "guild_memberships",
        sa.Column("oidc_provider_id", sa.Integer(), nullable=True),
    )
    if managed:
        moved = bind.execute(
            sa.text(
                "UPDATE guild_memberships SET oidc_provider_id = :pid "
                "WHERE oidc_managed"
            ),
            {"pid": platform_id},
        ).rowcount
        assert moved == managed, f"attributed {moved} of {managed} memberships"
    op.create_index(
        "ix_guild_memberships_oidc_provider_id",
        "guild_memberships",
        ["oidc_provider_id"],
    )
    op.create_foreign_key(
        "fk_guild_memberships_oidc_provider",
        "guild_memberships",
        "auth_providers",
        ["oidc_provider_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_column("guild_memberships", "oidc_managed")


def downgrade() -> None:
    op.add_column(
        "guild_memberships",
        sa.Column(
            "oidc_managed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.execute("ALTER TABLE guild_memberships NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(
            "UPDATE guild_memberships SET oidc_managed = true "
            "WHERE oidc_provider_id IS NOT NULL"
        )
    finally:
        op.execute("ALTER TABLE guild_memberships FORCE ROW LEVEL SECURITY")
    op.drop_constraint(
        "fk_guild_memberships_oidc_provider", "guild_memberships", type_="foreignkey"
    )
    op.drop_index("ix_guild_memberships_oidc_provider_id", "guild_memberships")
    op.drop_column("guild_memberships", "oidc_provider_id")

    op.drop_constraint(
        "fk_oidc_claim_mappings_provider", "oidc_claim_mappings", type_="foreignkey"
    )
    op.drop_index("ix_oidc_claim_mappings_provider_id", "oidc_claim_mappings")
    op.drop_column("oidc_claim_mappings", "provider_id")
