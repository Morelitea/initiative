"""property_values: one table for every tool's property values

Creates the guild-content ``property_values`` table, addressed by
``(entity_type, entity_id)``, moves the rows of ``task_property_values``,
``document_property_values`` and ``calendar_event_property_values`` into it,
then drops those three.

The new table records no ``created_by`` / ``updated_by``: a value belongs to the
initiative, not to whoever set it, so those columns are not carried over.

Each source is read in full for the copy, and the row counts are asserted to
match.

Order is create -> backfill -> drop. RLS, its policies and the grants are NOT
written here: provisioning renders those from the registries, and the boot
backfill re-applies them to every guild whose stamp this revision made stale.

Revision ID: 20261001_0432
Revises: 20261001_0431
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261001_0432"
down_revision = "20261001_0431"
branch_labels = None
depends_on = None


#: What may carry a property as of this revision — every tool and sub-tool.
#: Stated here rather than read from ``app.core.tools``: a target added later
#: widens the CHECK in a revision of its own.
_TARGETS = (
    "project",
    "document",
    "queue",
    "counter_group",
    "calendar",
    "dashboard",
    "post",
    "gallery",
    "wiki",
    "task",
    "queue_item",
    "calendar_event",
    "counter",
    "gallery_image",
    "wiki_page",
)

#: ``(old table, its key column, the target it becomes)``.
_SOURCES = (
    ("task_property_values", "task_id", "task"),
    ("document_property_values", "document_id", "document"),
    ("calendar_event_property_values", "event_id", "calendar_event"),
)

_VALUES = (
    "value_text, value_number, value_boolean, value_date, value_datetime, "
    "value_user_id, value_json"
)

#: The columns a property filter compares, each indexed by definition.
_FILTERED = (
    "value_text",
    "value_number",
    "value_date",
    "value_datetime",
    "value_user_id",
)


def _create_table() -> None:
    targets = ", ".join(f"'{t}'" for t in _TARGETS)
    op.create_table(
        "property_values",
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column(
            "property_id",
            sa.Integer(),
            sa.ForeignKey("property_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_number", sa.Numeric(), nullable=True),
        sa.Column("value_boolean", sa.Boolean(), nullable=True),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("value_datetime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("value_user_id", sa.Integer(), nullable=True),
        sa.Column("value_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("entity_type", "entity_id", "property_id"),
        sa.CheckConstraint(
            f"entity_type IN ({targets})", name="ck_property_values_entity_type"
        ),
    )
    op.create_index(
        "ix_property_values_property_id", "property_values", ["property_id"]
    )
    for column in _FILTERED:
        op.create_index(
            f"ix_property_values_{column}",
            "property_values",
            ["property_id", column],
            postgresql_where=sa.text(f"{column} IS NOT NULL"),
        )
    op.create_index(
        "ix_property_values_value_json",
        "property_values",
        ["value_json"],
        postgresql_using="gin",
        postgresql_ops={"value_json": "jsonb_path_ops"},
        postgresql_where=sa.text("value_json IS NOT NULL"),
    )


def _copy_sources() -> None:
    """Move the three tables in, asserting nothing was left behind."""
    bind = op.get_bind()
    for table, key, target in _SOURCES:
        if not bind.execute(
            sa.text("SELECT to_regclass(:t) IS NOT NULL"), {"t": table}
        ).scalar():
            continue

        # Read in full for the copy; the table is dropped right after.
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        expected = bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar()  # noqa: S608

        op.execute(f"""
            INSERT INTO property_values (
                entity_type, entity_id, property_id, {_VALUES}, created_at, updated_at
            )
            SELECT '{target}', s.{key}, s.property_id, {_VALUES},
                   s.created_at, s.updated_at
            FROM {table} s
        """)  # noqa: S608

        moved = bind.execute(
            sa.text("SELECT count(*) FROM property_values WHERE entity_type = :t"),
            {"t": target},
        ).scalar()
        if moved != expected:
            raise RuntimeError(
                f"{table}: copied {moved} of {expected} rows into property_values"
            )
        op.execute(f"DROP TABLE {table}")


def _apply_upgrade() -> None:
    _create_table()
    _copy_sources()


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_downgrade() -> None:
    """Rebuild the three tables from the values on tasks, documents and
    events, then drop the table.

    Values on anything else had nowhere to live before this revision, so they
    go with it. The rebuilt tables have the shape their rows need, not every
    index they once carried.
    """
    # Read in full for the copy; the table is dropped below.
    op.execute("ALTER TABLE property_values NO FORCE ROW LEVEL SECURITY")
    for table, key, target in _SOURCES:
        parent = {
            "task": "tasks",
            "document": "documents",
            "calendar_event": "calendar_events",
        }[target]
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                {key} integer NOT NULL REFERENCES {parent}(id) ON DELETE CASCADE,
                property_id integer NOT NULL
                    REFERENCES property_definitions(id) ON DELETE CASCADE,
                value_text text,
                value_number numeric,
                value_boolean boolean,
                value_date date,
                value_datetime timestamptz,
                value_user_id integer,
                value_json jsonb,
                created_at timestamptz NOT NULL,
                updated_at timestamptz NOT NULL,
                created_by integer,
                updated_by integer,
                PRIMARY KEY ({key}, property_id)
            )
        """)  # noqa: S608
        op.execute(f"""
            INSERT INTO {table} ({key}, property_id, {_VALUES}, created_at, updated_at)
            SELECT v.entity_id, v.property_id, {_VALUES}, v.created_at, v.updated_at
            FROM property_values v
            WHERE v.entity_type = '{target}'
              AND EXISTS (SELECT 1 FROM {parent} p WHERE p.id = v.entity_id)
        """)  # noqa: S608
    op.execute("DROP TABLE IF EXISTS property_values")


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)
