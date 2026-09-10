"""a task's checklist becomes a column on the task

``subtasks`` was a table with an id, an author and four policies for what it
actually held: a line of text, a tick-box and an order. Those lines move to
``tasks.checklist`` — an ordered JSONB array of ``{"id", "text", "done"}`` — and
the table goes.

Guild content, so this walks ``guild_template`` and every ``guild_<id>``. The
lines are carried before the table is dropped, and the count is asserted: both
tables force row-level security, their policies read request GUCs a migration
has no value for, and a fresh install has nothing to carry — so a silent zero
here would look exactly like success. The force is lifted for the carry and
restored whatever happens.

Item ids are minted here rather than derived from the old row ids: an id is
addressed by a tick, and a small integer that used to mean something else is a
worse name for that than a fresh one.

Revision ID: 20260910_0250
Revises: 20260910_0249
Create Date: 2026-09-10
"""

import logging

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import guild_schema_names

revision = "20260910_0250"
down_revision = "20260910_0249"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


_CARRY_FORWARD = """
    UPDATE tasks t
       SET checklist = sub.items
      FROM (
            SELECT task_id,
                   jsonb_agg(
                       jsonb_build_object(
                           'id', replace(gen_random_uuid()::text, '-', ''),
                           'text', content,
                           'done', is_completed
                       )
                       ORDER BY position, id
                   ) AS items
              FROM subtasks
             GROUP BY task_id
           ) sub
     WHERE t.id = sub.task_id
"""

_CARRY_BACK = """
    INSERT INTO subtasks (
        guild_id, task_id, content, is_completed, position, created_at, updated_at
    )
    SELECT t.guild_id,
           t.id,
           entry.elem->>'text',
           coalesce((entry.elem->>'done')::boolean, false),
           entry.ord - 1,
           now(),
           now()
      FROM tasks t
           CROSS JOIN LATERAL jsonb_array_elements(t.checklist)
                      WITH ORDINALITY AS entry(elem, ord)
     WHERE entry.elem->>'text' IS NOT NULL
"""


def _route(connection, schema: str) -> None:
    connection.execute(
        sa.text("SELECT set_config('search_path', :sp, true)"),
        {"sp": f'"{schema}", public'},
    )


def upgrade() -> None:
    connection = op.get_bind()
    tasks_touched = 0
    lines_carried = 0

    for schema in guild_schema_names(connection):
        _route(connection, schema)
        op.execute(
            "ALTER TABLE tasks ADD COLUMN checklist jsonb NOT NULL DEFAULT '[]'::jsonb"
        )
        op.execute("ALTER TABLE tasks NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE subtasks NO FORCE ROW LEVEL SECURITY")
        try:
            expected_tasks, expected_lines = connection.execute(
                sa.text("SELECT count(DISTINCT task_id), count(*) FROM subtasks")
            ).one()
            carried = connection.execute(sa.text(_CARRY_FORWARD)).rowcount
            if carried != expected_tasks:
                raise RuntimeError(
                    f"{schema}: {expected_tasks} task(s) hold checklist lines but "
                    f"{carried} were written — the carry did not reach every row"
                )
            tasks_touched += carried
            lines_carried += expected_lines
        finally:
            op.execute("ALTER TABLE tasks FORCE ROW LEVEL SECURITY")

        op.execute("DROP TABLE subtasks")
        # Delivery records naming a table that no longer exists; a consumer
        # reading one back would find nothing to read.
        op.execute("DELETE FROM event_outbox WHERE resource_type = 'subtasks'")

    connection.execute(sa.text("SET LOCAL search_path = public"))
    logger.info(
        "checklists carried onto their tasks: %s line(s) across %s task(s)",
        lines_carried,
        tasks_touched,
    )


def downgrade() -> None:
    """Put the table back and unpack every checklist into it.

    Row-level security on the recreated table arrives the way it does for any
    guild table: the registry that renders it names ``subtasks`` again in the
    code being downgraded to, and the provisioning stamp is re-applied on the
    next boot. Per-item authorship does not come back — the column never
    carried it.
    """
    connection = op.get_bind()
    lines_carried = 0

    for schema in guild_schema_names(connection):
        _route(connection, schema)
        op.create_table(
            "subtasks",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("guild_id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column(
                "is_completed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "position", sa.Integer(), nullable=False, server_default=sa.text("0")
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["task_id"],
                ["tasks.id"],
                name="fk_subtasks_task_id",
                ondelete="CASCADE",
            ),
        )
        op.create_index("ix_subtasks_guild_id", "subtasks", ["guild_id"])
        op.create_index("ix_subtasks_task_id", "subtasks", ["task_id"])

        op.execute("ALTER TABLE tasks NO FORCE ROW LEVEL SECURITY")
        try:
            lines_carried += connection.execute(sa.text(_CARRY_BACK)).rowcount
        finally:
            op.execute("ALTER TABLE tasks FORCE ROW LEVEL SECURITY")

        op.execute("ALTER TABLE tasks DROP COLUMN checklist")

    connection.execute(sa.text("SET LOCAL search_path = public"))
    logger.info("checklists unpacked back into subtasks: %s line(s)", lines_carried)
