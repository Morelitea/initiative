"""Add general-access (all-initiative-members) share column to resource_grants.

Adds a single ``all_initiative_members`` boolean and swaps the
``resource_grants_one_grantee`` check from the old user-XOR-role to "exactly one
grantee kind" (user, role, OR the whole initiative). A share row has no
user_id/role_id, ``all_initiative_members = true`` and its level in the existing
``level`` column (read = Viewer, write = Editor); the boolean may not be set when
a user/role grantee is present.

Applied to ``public`` (the reflection source for guild_schema.sql) AND every
existing ``guild_*`` schema — the generated guild_schema.sql only
``CREATE TABLE IF NOT EXISTS`` (a no-op on existing tables), so the new column
reaches existing guilds only via this explicit ALTER. New guilds pick it up from
the regenerated guild_schema.sql. See history/general-access-sharing-design.md.

Revision ID: 20260617_0117
Revises: 20260616_0116
Create Date: 2026-06-17
"""

from alembic import op
from sqlalchemy import text

revision = "20260617_0117"
down_revision = "20260616_0116"
branch_labels = None
depends_on = None

_NEW_CHECK = (
    "(user_id IS NOT NULL)::int + (role_id IS NOT NULL)::int "
    "+ (all_initiative_members)::int = 1"
)
_OLD_CHECK = "(user_id IS NULL) <> (role_id IS NULL)"


def _guild_schemas(conn) -> list[str]:
    # Matches every guild_<id> AND guild_template.
    rows = conn.execute(
        text("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'guild\\_%'")
    ).all()
    return [r[0] for r in rows]


def _apply(conn) -> None:
    """Idempotently add the share column + set the grantee check on the
    ``resource_grants`` table resolved by the current search_path."""
    conn.execute(
        text(
            "ALTER TABLE resource_grants "
            "ADD COLUMN IF NOT EXISTS all_initiative_members "
            "BOOLEAN NOT NULL DEFAULT FALSE"
        )
    )
    conn.execute(
        text(
            "ALTER TABLE resource_grants DROP CONSTRAINT IF EXISTS resource_grants_one_grantee"
        )
    )
    conn.execute(
        text(
            "ALTER TABLE resource_grants ADD CONSTRAINT resource_grants_one_grantee "
            f"CHECK ({_NEW_CHECK})"
        )
    )


def _revert(conn) -> None:
    """Drop the share column + restore the old XOR check on the search-path
    ``resource_grants``. Share rows (no grantee) violate the XOR, so clear them
    first."""
    conn.execute(
        text("DELETE FROM resource_grants WHERE user_id IS NULL AND role_id IS NULL")
    )
    conn.execute(
        text(
            "ALTER TABLE resource_grants DROP CONSTRAINT IF EXISTS resource_grants_one_grantee"
        )
    )
    conn.execute(
        text(
            "ALTER TABLE resource_grants ADD CONSTRAINT resource_grants_one_grantee "
            f"CHECK ({_OLD_CHECK})"
        )
    )
    conn.execute(
        text("ALTER TABLE resource_grants DROP COLUMN IF EXISTS all_initiative_members")
    )


def upgrade() -> None:
    conn = op.get_bind()
    for schema in _guild_schemas(conn):
        conn.execute(text(f'SET search_path TO "{schema}", public'))
        _apply(conn)
    conn.execute(text("SET search_path TO public"))
    _apply(conn)


def downgrade() -> None:
    conn = op.get_bind()
    for schema in _guild_schemas(conn):
        conn.execute(text(f'SET search_path TO "{schema}", public'))
        _revert(conn)
    conn.execute(text("SET search_path TO public"))
    _revert(conn)
