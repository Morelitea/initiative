"""stored values say community

The API names communities as communities, so the values it reads back out of
rows do too: the four community notification types, the ``guild_id`` and
``guild_name`` keys of a notification's payload (and a queued push's), an
export of a whole community (``source``, and the payloads that name it), the
AI mode a community configures itself, and the connection scope its
connections are keyed by.

A backup's manifest still records its scope as ``guild``: files already on
disk must keep importing.

Revision ID: 20261003_0445
Revises: 20261002_0444
Create Date: 2026-10-03
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261003_0445"
down_revision = "20261002_0444"
branch_labels = None
depends_on = None

NOTIFICATION_TYPES = {
    "guild_on_hold": "community_on_hold",
    "guild_trial_ending": "community_trial_ending",
    "guild_trial_ended": "community_trial_ended",
    "guild_welcome": "community_welcome",
}
PAYLOAD_KEYS = {"guild_id": "community_id", "guild_name": "community_name"}
EXPORT_NOTICES = ("export_ready", "export_failed")


def _forced(bind, table: str) -> bool:
    return bool(
        bind.execute(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    )


def _unforced(bind, tables: tuple[str, ...], write) -> None:
    """Run ``write`` with the owner's RLS lifted on ``tables`` and their user
    triggers held, both restored after."""
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


def _none_left(bind, table: str, where: str) -> None:
    left = bind.execute(sa.text(f"SELECT count(*) FROM {table} WHERE {where}")).scalar()
    if left:
        raise RuntimeError(f"{left} rows of {table} still match {where}")


def _set_value(bind, table: str, column: str, values: dict[str, str]) -> None:
    for old, new in values.items():
        bind.execute(
            sa.text(f"UPDATE {table} SET {column} = :new WHERE {column} = :old"),
            {"old": old, "new": new},
        )
    olds = ", ".join(f"'{old}'" for old in values)
    _none_left(bind, table, f"{column} IN ({olds})")


def _rename_keys(bind, table: str, column: str, keys: dict[str, str], cast: str):
    """Rename top-level keys of a JSON column, keeping each value as it was."""
    for old, new in keys.items():
        doc = f"{column}::jsonb"
        bind.execute(
            sa.text(
                f"UPDATE {table} SET {column} = "
                f"(({doc} - '{old}') || jsonb_build_object('{new}', {doc} -> '{old}'))"
                f"{cast} WHERE {column} IS NOT NULL AND {doc} ? '{old}'"
            )
        )
        _none_left(bind, table, f"{column} IS NOT NULL AND {column}::jsonb ? '{old}'")


def _export_source(bind, table: str, column: str, source: tuple[str, str], cast: str):
    """An export notice names the community export by its source."""
    old, new = source
    types = ", ".join(f"'{t}'" for t in EXPORT_NOTICES)
    doc = f"{column}::jsonb"
    where = f"type IN ({types}) AND {doc} ->> 'source' = '{old}'"
    bind.execute(
        sa.text(
            f"UPDATE {table} SET {column} = "
            f"jsonb_set({doc}, '{{source}}', to_jsonb('{new}'::text)){cast} "
            f"WHERE {where}"
        )
    )
    _none_left(bind, table, where)


def _public(bind, types: dict[str, str], keys: dict[str, str], source, mode) -> None:
    notifications = "public.notifications"
    outbox = "public.notice_outbox"
    settings = "public.app_settings"

    def write() -> None:
        _set_value(bind, notifications, "type", types)
        _rename_keys(bind, notifications, "data", keys, "::json")
        _export_source(bind, notifications, "data", source, "::json")
        _set_value(bind, outbox, "type", types)
        _rename_keys(bind, outbox, "data", keys, "")
        _rename_keys(bind, outbox, "push_data", keys, "")
        _export_source(bind, outbox, "data", source, "")
        _set_value(bind, settings, "ai_config_mode", mode)

    _unforced(bind, (notifications, outbox, settings), write)


def _guild(bind, scope: dict[str, str], source: dict[str, str]) -> None:
    tables = ("guild_ai_member_keys", "guild_ai_member_prefs", "export_jobs")

    def write() -> None:
        _set_value(bind, "guild_ai_member_keys", "connection_scope", scope)
        _set_value(bind, "guild_ai_member_prefs", "connection_scope", scope)
        _set_value(bind, "export_jobs", "source", source)

    _unforced(bind, tables, write)


def upgrade() -> None:
    bind = op.get_bind()
    _public(
        bind,
        NOTIFICATION_TYPES,
        PAYLOAD_KEYS,
        ("guild", "community"),
        {"guild": "community"},
    )
    run_for_each_guild_schema(
        bind, lambda: _guild(bind, {"guild": "community"}, {"guild": "community"})
    )


def downgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(
        bind, lambda: _guild(bind, {"community": "guild"}, {"community": "guild"})
    )
    _public(
        bind,
        {new: old for old, new in NOTIFICATION_TYPES.items()},
        {new: old for old, new in PAYLOAD_KEYS.items()},
        ("community", "guild"),
        {"community": "guild"},
    )
