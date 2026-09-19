"""every comment knows which community it is in

``comments.guild_id`` is denormalized by a trigger — ``public.fn_comments_set_guild_id``
reads it off whichever parent the row names. The function and the per-schema
trigger were last written in 0192, when the parents ended at ``dashboard_id``.
Posts, galleries and wikis arrived afterwards and none of them extended it, so
a comment on one of those was written with ``guild_id`` NULL: its thread read
back fine (the thread is selected by its parent column), but the guild-wide
recent-activity feed filters on ``guild_id`` and so has never shown one.

This rebuilds both from the full parent list — the tools plus the content-level
extras, ``wiki_page_id`` among them — and repairs the rows already written.

``comment_guild_id_test`` holds the live definitions to the parent registry
from here on, so the next parent cannot arrive without them.
"""

from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260918_0317"
down_revision = "20260918_0316"
branch_labels = None
depends_on = None

#: Every comment parent and the table it points at, in the order the registry
#: declares them. Frozen here rather than imported: a migration is a snapshot
#: of one moment, and this one must keep emitting these arms after the registry
#: has moved on.
_PARENTS: tuple[tuple[str, str], ...] = (
    ("task_id", "tasks"),
    ("wiki_page_id", "wiki_pages"),
    ("project_id", "projects"),
    ("document_id", "documents"),
    ("queue_id", "queues"),
    ("counter_group_id", "counter_groups"),
    ("calendar_id", "calendars"),
    ("dashboard_id", "dashboards"),
    ("post_id", "posts"),
    ("gallery_id", "galleries"),
    ("wiki_id", "wikis"),
)

#: The set as 0192 left it — what a downgrade restores.
_PARENTS_BEFORE: tuple[tuple[str, str], ...] = (
    ("task_id", "tasks"),
    ("document_id", "documents"),
    ("project_id", "projects"),
    ("queue_id", "queues"),
    ("counter_group_id", "counter_groups"),
    ("calendar_id", "calendars"),
    ("dashboard_id", "dashboards"),
)


def _guild_id_fn(parents: tuple[tuple[str, str], ...]) -> str:
    """The trigger function, one arm per parent.

    The parent tables are named unqualified on purpose: the function is shared
    in ``public`` and carries no ``search_path``, so each call resolves them in
    the guild schema the statement is running in.
    """
    changed = "\n                    OR ".join(
        f"OLD.{column} IS DISTINCT FROM NEW.{column}" for column, _ in parents
    )
    arms = "\n                ".join(
        f"{'IF' if index == 0 else 'ELSIF'} NEW.{column} IS NOT NULL THEN\n"
        f"                    SELECT guild_id INTO NEW.guild_id "
        f"FROM {table} WHERE id = NEW.{column};"
        for index, (column, table) in enumerate(parents)
    )
    return f"""
CREATE OR REPLACE FUNCTION public.fn_comments_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR
               (TG_OP = 'UPDATE' AND ({changed})) THEN
                {arms}
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
"""


def _trigger_ddl(parents: tuple[tuple[str, str], ...]) -> str:
    columns = ", ".join(column for column, _ in parents)
    return (
        "CREATE OR REPLACE TRIGGER tr_comments_set_guild_id "
        f"BEFORE INSERT OR UPDATE OF {columns} ON comments "
        "FOR EACH ROW EXECUTE FUNCTION public.fn_comments_set_guild_id()"
    )


def _repair(parents: tuple[tuple[str, str], ...]) -> None:
    """Fill in the guild of every comment written while its parent had no arm.

    ``comments`` already carries FORCE ROW LEVEL SECURITY, and this migration
    runs as the table's owner with no request context for the policies to read,
    so the force is lifted for the write and restored either way.
    """
    op.execute("ALTER TABLE comments NO FORCE ROW LEVEL SECURITY")
    try:
        for column, table in parents:
            op.execute(
                "UPDATE comments SET guild_id = "  # noqa: S608 — names frozen above
                f"(SELECT guild_id FROM {table} WHERE id = comments.{column}) "
                f"WHERE guild_id IS NULL AND {column} IS NOT NULL"
            )
    finally:
        op.execute("ALTER TABLE comments FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    # The function is shared in public — replaced once, outside the loop.
    op.execute(_guild_id_fn(_PARENTS))
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.execute(_trigger_ddl(_PARENTS))
    _repair(_PARENTS)


def downgrade() -> None:
    op.execute(_guild_id_fn(_PARENTS_BEFORE))
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    op.execute(_trigger_ddl(_PARENTS_BEFORE))
