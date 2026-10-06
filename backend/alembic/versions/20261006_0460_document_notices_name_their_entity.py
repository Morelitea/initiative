"""document notices name their entity

A comment or mention notice about a document names it the way every other
tool's does: ``entity_type`` and ``entity_id`` (``context_entity_type`` and
``context_entity_id`` on a ``#task`` mention made in its thread) rather than
``document_id`` and ``context_document_id``. Unread lines never expire, so the
stored ones are rewritten, with the notices still queued.

Revision ID: 20261006_0460
Revises: 20261005_0459
Create Date: 2026-10-06
"""

import sqlalchemy as sa
from alembic import op

revision = "20261006_0460"
down_revision = "20261005_0459"
branch_labels = None
depends_on = None

#: The notice types that named a document by its own key.
TYPES = "type IN ('mention', 'comment_reply')"
NOTIFICATIONS = "public.notifications"
OUTBOX = "public.notice_outbox"
#: (table, payload column, cast back to the column's type)
PAYLOADS = ((NOTIFICATIONS, "data", "::json"), (OUTBOX, "data", ""))
#: (old key, new id key, new type key)
KEYS = (
    ("document_id", "entity_id", "entity_type"),
    ("context_document_id", "context_entity_id", "context_entity_type"),
)


def _forced(bind, table: str) -> bool:
    return bool(
        bind.execute(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    )


def _unforced(bind, write) -> None:
    """Run ``write`` with the owner's RLS lifted on both tables and their user
    triggers held, both restored after."""
    tables = (NOTIFICATIONS, OUTBOX)
    forced = [table for table in tables if _forced(bind, table)]
    for table in forced:
        bind.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
    for table in tables:
        bind.execute(sa.text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
    try:
        write()
    finally:
        for table in tables:
            bind.execute(sa.text(f"ALTER TABLE {table} ENABLE TRIGGER USER"))
        for table in forced:
            bind.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))


def _forward(bind) -> None:
    for old, id_key, type_key in KEYS:
        # A queued push carries the ids alone, as strings, and only set ones.
        bind.execute(
            sa.text(
                f"UPDATE {OUTBOX} SET push_data = (push_data - '{old}') "
                f"|| jsonb_build_object('{id_key}', push_data -> '{old}') "
                f"WHERE {TYPES} AND push_data ? '{old}'"
            )
        )
        # Only notices that name a document: a task's notice carried the key
        # empty, and nothing reads it now, so those rows are left unwritten.
        for table, column, cast in PAYLOADS:
            doc = f"{column}::jsonb"
            bind.execute(
                sa.text(
                    f"UPDATE {table} SET {column} = (({doc} - '{old}') || "
                    f"jsonb_build_object('{type_key}', 'document', "
                    f"'{id_key}', {doc} -> '{old}')){cast} "
                    f"WHERE {TYPES} AND jsonb_typeof({doc} -> '{old}') <> 'null'"
                )
            )


def _backward(bind) -> None:
    for old, id_key, type_key in KEYS:
        # Before the payload loses the type that says which ids were documents.
        bind.execute(
            sa.text(
                f"UPDATE {OUTBOX} SET push_data = (push_data - '{id_key}') "
                f"|| jsonb_build_object('{old}', push_data -> '{id_key}') "
                f"WHERE {TYPES} AND data ->> '{type_key}' = 'document' "
                f"AND push_data ? '{id_key}'"
            )
        )
        # A ``#task`` mention carried both context keys, empty, beside a
        # document's; a thread's own keys were left out for one.
        keep = (
            f"jsonb_build_object('{type_key}', NULL, '{id_key}', NULL)"
            if old.startswith("context_")
            else "'{}'::jsonb"
        )
        for table, column, cast in PAYLOADS:
            doc = f"{column}::jsonb"
            bind.execute(
                sa.text(
                    f"UPDATE {table} SET {column} = ({doc} - '{type_key}' - '{id_key}' "
                    f"|| {keep} || jsonb_build_object('{old}', {doc} -> '{id_key}'))"
                    f"{cast} WHERE {TYPES} AND {doc} ->> '{type_key}' = 'document'"
                )
            )


def upgrade() -> None:
    bind = op.get_bind()
    _unforced(bind, lambda: _forward(bind))


def downgrade() -> None:
    bind = op.get_bind()
    _unforced(bind, lambda: _backward(bind))
