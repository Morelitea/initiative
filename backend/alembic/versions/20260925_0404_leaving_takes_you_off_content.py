"""leaving takes you off content

Leaving an initiative now takes the person off its content as well as its
grants (``tr_initiative_members_departure`` and ``public.member_departs``,
rendered by provisioning): task assignees, event attendees, person-valued
fields and the person on a queue item. Leaving the community does the same
for its own content.

This removes the ones earlier departures left: a person named on content of
an initiative they are not a member of, or on the community's own content
when they are not a member of the community. A queue item stays, with no
person. Not restored by the downgrade.

The statements are stated here in full, so this revision reads the same
whatever the modules say later.

Revision ID: 20260925_0404
Revises: 20260925_0403
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import guild_schema_names

revision = "20260925_0404"
down_revision = "20260925_0403"
branch_labels = None
depends_on = None

#: Each place content names a person: the table, its person column, the
#: initiative a row belongs to, and whether the row is kept with the column
#: emptied rather than deleted.
_NAMED = (
    (
        "task_assignees",
        "user_id",
        "(SELECT p.initiative_id FROM {s}.tasks k JOIN {s}.projects p"
        " ON p.id = k.project_id WHERE k.id = t.task_id)",
        False,
    ),
    (
        "task_property_values",
        "value_user_id",
        "(SELECT p.initiative_id FROM {s}.tasks k JOIN {s}.projects p"
        " ON p.id = k.project_id WHERE k.id = t.task_id)",
        False,
    ),
    (
        "calendar_event_attendees",
        "user_id",
        "(SELECT c.initiative_id FROM {s}.calendar_events e JOIN {s}.calendars c"
        " ON c.id = e.calendar_id WHERE e.id = t.calendar_event_id)",
        False,
    ),
    (
        "calendar_event_property_values",
        "value_user_id",
        "(SELECT c.initiative_id FROM {s}.calendar_events e JOIN {s}.calendars c"
        " ON c.id = e.calendar_id WHERE e.id = t.event_id)",
        False,
    ),
    (
        "document_property_values",
        "value_user_id",
        "(SELECT d.initiative_id FROM {s}.documents d WHERE d.id = t.document_id)",
        False,
    ),
    (
        "queue_items",
        "user_id",
        "(SELECT q.initiative_id FROM {s}.queues q WHERE q.id = t.queue_id)",
        True,
    ),
)

#: The guild tables the statements read, beside the named ones.
_READ = (
    "tasks",
    "projects",
    "calendar_events",
    "calendars",
    "documents",
    "queues",
    "initiative_members",
)


def _stray(schema: str, guild_id: int, column: str, initiative: str) -> str:
    """The rows naming someone who is not in the row's initiative, or, on the
    community's own content, not in the community."""
    initiative = initiative.format(s=schema)
    return (
        f"t.{column} IS NOT NULL AND CASE WHEN {initiative} IS NULL"
        " THEN NOT EXISTS (SELECT 1 FROM public.guild_memberships gm"
        f" WHERE gm.guild_id = {guild_id} AND gm.user_id = t.{column})"
        f" ELSE NOT EXISTS (SELECT 1 FROM {schema}.initiative_members m"
        f" WHERE m.initiative_id = {initiative} AND m.user_id = t.{column}) END"
    )


def _take_off(bind, schema: str) -> None:
    """Remove ``schema``'s strays. Every table read is FORCE RLS and a migration
    carries no request context, so the owner's policies are lifted before
    anything reads them and restored after; the named tables' triggers (the
    freeze, the change capture) are about requests and are held while rows
    change."""
    guild_id = int(schema.removeprefix("guild_"))
    members = sa.text(
        f"SELECT count(*) FROM public.guild_memberships WHERE guild_id = {guild_id}"
    )
    if not bind.execute(members).scalar():
        # A community with nobody in it reads the same as one whose members
        # could not be read; leave it.
        return
    tables = [f"{schema}.{t}" for t, *_ in _NAMED] + [f"{schema}.{t}" for t in _READ]
    for table in tables:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    try:
        for table, column, initiative, clear in _NAMED:
            where = _stray(schema, guild_id, column, initiative)
            count = sa.text(f"SELECT count(*) FROM {schema}.{table} t WHERE {where}")
            stray = bind.execute(count).scalar()
            if not stray:
                continue
            op.execute(f"ALTER TABLE {schema}.{table} DISABLE TRIGGER USER")
            if clear:
                op.execute(
                    f"UPDATE {schema}.{table} t SET {column} = NULL WHERE {where}"
                )
            else:
                op.execute(f"DELETE FROM {schema}.{table} t WHERE {where}")
            op.execute(f"ALTER TABLE {schema}.{table} ENABLE TRIGGER USER")
            left = bind.execute(count).scalar()
            assert left == 0, f"{schema}.{table}: {left} of {stray} remain"
    finally:
        for table in tables:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("ALTER TABLE public.guild_memberships NO FORCE ROW LEVEL SECURITY")
    try:
        for schema in guild_schema_names(bind):
            if schema.removeprefix("guild_").isdigit():
                _take_off(bind, schema)
    finally:
        op.execute("ALTER TABLE public.guild_memberships FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    pass
