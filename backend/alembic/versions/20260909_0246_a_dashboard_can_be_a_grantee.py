"""A grant may name a dashboard

``resource_grants`` has carried exactly one grantee per row — a user, an
initiative role, or every initiative member. This adds a fourth: a dashboard.
A row naming one says the resource is readable *through* that dashboard, which
is what a published view is made of.

Read-only by construction. The CHECK below admits a dashboard grantee only at
``level = 'read'``, so the level-aware leg of ``public.resource_access`` can
never answer a write with one.

The column is nullable and every existing row leaves it NULL, so the grants a
guild already holds are untouched and the new CHECK admits them unchanged.

Revision ID: 20260909_0246
Revises: 20260909_0245
Create Date: 2026-09-09
"""

from alembic import op

from app.db.guild_migrations import apply_to_all_guild_schemas

revision = "20260909_0246"
down_revision = "20260909_0245"
branch_labels = None
depends_on = None

#: The grantee test, before and after. One kind per row either way.
_ONE_GRANTEE_BEFORE = (
    "(user_id IS NOT NULL)::int + (role_id IS NOT NULL)::int "
    "+ (all_initiative_members)::int = 1"
)
_ONE_GRANTEE_AFTER = (
    "(user_id IS NOT NULL)::int + (role_id IS NOT NULL)::int "
    "+ (all_initiative_members)::int + (dashboard_id IS NOT NULL)::int = 1"
)

#: The uniqueness of a grantee on a resource. NULLS NOT DISTINCT so the unused
#: grantee columns compare equal — otherwise two grants differing only in which
#: column is NULL would not collide.
_UNIQUE_BEFORE = "(resource_type, resource_id, user_id, role_id)"
_UNIQUE_AFTER = "(resource_type, resource_id, user_id, role_id, dashboard_id)"


def _swap(one_grantee: str, unique: str) -> tuple[str, ...]:
    return (
        "ALTER TABLE resource_grants DROP CONSTRAINT resource_grants_one_grantee",
        f"ALTER TABLE resource_grants ADD CONSTRAINT resource_grants_one_grantee "
        f"CHECK ({one_grantee})",
        "ALTER TABLE resource_grants DROP CONSTRAINT resource_grants_unique_grantee",
        f"ALTER TABLE resource_grants ADD CONSTRAINT resource_grants_unique_grantee "
        f"UNIQUE NULLS NOT DISTINCT {unique}",
    )


def upgrade() -> None:
    apply_to_all_guild_schemas(
        op.get_bind(),
        "ALTER TABLE resource_grants ADD COLUMN dashboard_id integer "
        "REFERENCES dashboards(id) ON DELETE CASCADE",
        *_swap(_ONE_GRANTEE_AFTER, _UNIQUE_AFTER),
        "ALTER TABLE resource_grants ADD CONSTRAINT resource_grants_dashboard_reads "
        "CHECK (dashboard_id IS NULL OR level = 'read')",
        # What a dashboard publishes over, which is the question the sharing
        # panel and the fetch path both ask.
        "CREATE INDEX ix_resource_grants_dashboard ON resource_grants (dashboard_id) "
        "WHERE dashboard_id IS NOT NULL",
    )


def downgrade() -> None:
    apply_to_all_guild_schemas(
        op.get_bind(),
        # The rows go with the column: a grant naming a dashboard has no
        # meaning once nothing can name one.
        "DELETE FROM resource_grants WHERE dashboard_id IS NOT NULL",
        "DROP INDEX IF EXISTS ix_resource_grants_dashboard",
        "ALTER TABLE resource_grants DROP CONSTRAINT resource_grants_dashboard_reads",
        *_swap(_ONE_GRANTEE_BEFORE, _UNIQUE_BEFORE),
        "ALTER TABLE resource_grants DROP COLUMN dashboard_id",
    )
