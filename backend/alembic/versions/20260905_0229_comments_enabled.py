"""state the comment switch positively

``comments_disabled`` becomes ``comments_enabled`` on all seven tool tables,
with the values flipped and the default now "on". The switch reads the same
way it is labelled, so nobody has to answer yes to mean no.

The flip is a column rewrite (``ALTER COLUMN … TYPE boolean USING NOT …``)
rather than an UPDATE, so each table inverts in a single pass.

Revision ID: 20260905_0229
Revises: 20260905_0228
Create Date: 2026-09-05
"""

from alembic import op

from app.db.guild_migrations import apply_to_all_guild_schemas

revision = "20260905_0229"
down_revision = "20260905_0228"
branch_labels = None
depends_on = None


# Every tool's content table — the tables carrying the switch at this revision.
_TABLES = (
    "projects",
    "documents",
    "queues",
    "counter_groups",
    "calendars",
    "dashboards",
    "posts",
)


def _statements(old: str, new: str, default: str) -> tuple[str, ...]:
    return tuple(
        statement
        for table in _TABLES
        for statement in (
            f"ALTER TABLE {table} ALTER COLUMN {old} DROP DEFAULT",
            f"ALTER TABLE {table} ALTER COLUMN {old} TYPE boolean USING NOT {old}",
            f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}",
            f"ALTER TABLE {table} ALTER COLUMN {new} SET DEFAULT {default}",
        )
    )


def upgrade() -> None:
    apply_to_all_guild_schemas(
        op.get_bind(),
        *_statements("comments_disabled", "comments_enabled", "true"),
    )


def downgrade() -> None:
    apply_to_all_guild_schemas(
        op.get_bind(),
        *_statements("comments_enabled", "comments_disabled", "false"),
    )
