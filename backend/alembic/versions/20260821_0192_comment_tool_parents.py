"""comment tool parents

Every tool entity becomes a comment parent. ``comments`` gains one nullable FK
per tool (``project_id``, ``queue_id``, ``counter_group_id``, ``calendar_id``,
``dashboard_id``) alongside the original ``task_id``/``document_id`` pair, and
the two-way XOR check becomes a single-parent ``num_nonnulls(...) = 1`` check.

``public.fn_comments_set_guild_id`` (the guild_id denormalization trigger
function, shared in ``public``) learns the new parents, and the per-schema
trigger re-fires on changes to any parent column.

The RLS policy legs and the outbox initiative locator for ``comments`` render
from ``app.db.initiative_rls._COMMENT_PARENTS`` at provisioning time; the
registry change bumps the provisioning stamp so existing schemas pick them up
on the next boot backfill.
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260821_0192"
down_revision = "20260820_0191"
branch_labels = None
depends_on = None

#: The new tool parents, in column order. Each references the table's ``id``
#: and cascades with it, exactly like the original task/document parents.
_NEW_PARENTS: tuple[tuple[str, str], ...] = (
    ("project_id", "projects"),
    ("queue_id", "queues"),
    ("counter_group_id", "counter_groups"),
    ("calendar_id", "calendars"),
    ("dashboard_id", "dashboards"),
)

_ALL_PARENT_COLUMNS = ("task_id", "document_id") + tuple(c for c, _ in _NEW_PARENTS)

_SINGLE_PARENT_CHECK = "num_nonnulls(" + ", ".join(_ALL_PARENT_COLUMNS) + ") = 1"

#: guild_id resolution, one leg per parent. Same shape as the prior definition
#: (baseline 0125), extended to the tool parents.
_GUILD_ID_FN = """
CREATE OR REPLACE FUNCTION public.fn_comments_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR
               (TG_OP = 'UPDATE' AND (OLD.task_id IS DISTINCT FROM NEW.task_id
                    OR OLD.document_id IS DISTINCT FROM NEW.document_id
                    OR OLD.project_id IS DISTINCT FROM NEW.project_id
                    OR OLD.queue_id IS DISTINCT FROM NEW.queue_id
                    OR OLD.counter_group_id IS DISTINCT FROM NEW.counter_group_id
                    OR OLD.calendar_id IS DISTINCT FROM NEW.calendar_id
                    OR OLD.dashboard_id IS DISTINCT FROM NEW.dashboard_id)) THEN
                IF NEW.task_id IS NOT NULL THEN
                    SELECT guild_id INTO NEW.guild_id FROM tasks WHERE id = NEW.task_id;
                ELSIF NEW.document_id IS NOT NULL THEN
                    SELECT guild_id INTO NEW.guild_id FROM documents WHERE id = NEW.document_id;
                ELSIF NEW.project_id IS NOT NULL THEN
                    SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;
                ELSIF NEW.queue_id IS NOT NULL THEN
                    SELECT guild_id INTO NEW.guild_id FROM queues WHERE id = NEW.queue_id;
                ELSIF NEW.counter_group_id IS NOT NULL THEN
                    SELECT guild_id INTO NEW.guild_id FROM counter_groups WHERE id = NEW.counter_group_id;
                ELSIF NEW.calendar_id IS NOT NULL THEN
                    SELECT guild_id INTO NEW.guild_id FROM calendars WHERE id = NEW.calendar_id;
                ELSIF NEW.dashboard_id IS NOT NULL THEN
                    SELECT guild_id INTO NEW.guild_id FROM dashboards WHERE id = NEW.dashboard_id;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
"""

#: The definition this replaces (baseline 0125), restored on downgrade.
_GUILD_ID_FN_PRIOR = """
CREATE OR REPLACE FUNCTION public.fn_comments_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR
               (TG_OP = 'UPDATE' AND (OLD.task_id IS DISTINCT FROM NEW.task_id OR OLD.document_id IS DISTINCT FROM NEW.document_id)) THEN
                IF NEW.task_id IS NOT NULL THEN
                    SELECT guild_id INTO NEW.guild_id FROM tasks WHERE id = NEW.task_id;
                ELSIF NEW.document_id IS NOT NULL THEN
                    SELECT guild_id INTO NEW.guild_id FROM documents WHERE id = NEW.document_id;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
"""


def _trigger_ddl(columns: tuple[str, ...]) -> str:
    return (
        "CREATE OR REPLACE TRIGGER tr_comments_set_guild_id "
        f"BEFORE INSERT OR UPDATE OF {', '.join(columns)} ON comments "
        "FOR EACH ROW EXECUTE FUNCTION public.fn_comments_set_guild_id()"
    )


def upgrade() -> None:
    # The trigger function is shared in public — applied once, outside the loop.
    op.execute(_GUILD_ID_FN)
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    with op.batch_alter_table("comments", schema=None) as batch_op:
        for column, _table in _NEW_PARENTS:
            batch_op.add_column(sa.Column(column, sa.Integer(), nullable=True))

    for column, table in _NEW_PARENTS:
        op.create_foreign_key(
            f"comments_{column}_fkey",
            "comments",
            table,
            [column],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_index(f"ix_comments_{column}", "comments", [column])

    op.drop_constraint("ck_comments_task_or_document", "comments", type_="check")
    op.create_check_constraint(
        "ck_comments_single_parent", "comments", _SINGLE_PARENT_CHECK
    )

    op.execute(_trigger_ddl(_ALL_PARENT_COLUMNS))


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)
    op.execute(_GUILD_ID_FN_PRIOR)


def _apply_downgrade() -> None:
    # Rows on tool parents have no place in the two-parent shape.
    op.execute(
        "DELETE FROM comments WHERE num_nonnulls("
        + ", ".join(c for c, _ in _NEW_PARENTS)
        + ") > 0"
    )

    op.execute(_trigger_ddl(("task_id", "document_id")))

    op.drop_constraint("ck_comments_single_parent", "comments", type_="check")
    op.create_check_constraint(
        "ck_comments_task_or_document",
        "comments",
        "(task_id IS NULL) <> (document_id IS NULL)",
    )

    for column, _table in reversed(_NEW_PARENTS):
        op.drop_index(f"ix_comments_{column}", table_name="comments")
        op.drop_constraint(f"comments_{column}_fkey", "comments", type_="foreignkey")

    with op.batch_alter_table("comments", schema=None) as batch_op:
        for column, _table in reversed(_NEW_PARENTS):
            batch_op.drop_column(column)
