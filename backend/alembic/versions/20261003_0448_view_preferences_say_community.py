"""view preferences say community

The app names a community as a community in the view state it keeps for each
person, so the rows it reads back say so too: a pinned task in the my-tasks
focus list (``pins[].guild_id``), and the community filter of the my-tasks list
and the my-calendar page (``guildFilters``).

The app opens a notification's link with ``/navigate?community_id=``, so the
links stored with notifications, and with notices still queued for email, say
so as well.

Revision ID: 20261003_0448
Revises: 20261003_0447
Create Date: 2026-10-03
"""

import sqlalchemy as sa
from alembic import op

revision = "20261003_0448"
down_revision = "20261003_0447"
branch_labels = None
depends_on = None

PREFERENCES = "public.user_view_preferences"
FOCUS_SCOPE = "my-tasks:focus"
FILTER_SCOPES = ("initiative-my-tasks-filters", "initiative-my-calendar-prefs")

#: ``(old, new)`` for a pin's key, the filter key and the link's query, in
#: that order.
FORWARD = (
    ("guild_id", "community_id"),
    ("guildFilters", "communityFilters"),
    ("/navigate?guild_id=", "/navigate?community_id="),
)
BACKWARD = tuple((new, old) for old, new in FORWARD)


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


def _none_left(bind, table: str, where: str, params: dict) -> None:
    left = bind.execute(
        sa.text(f"SELECT count(*) FROM {table} WHERE {where}"), params
    ).scalar()
    if left:
        raise RuntimeError(f"{left} rows of {table} still match {where}")


def _pins(bind, old: str, new: str) -> None:
    """Rename the key of every pin in the focus list, keeping its order."""
    doc = "value::jsonb"
    has_old = "jsonb_typeof(pin) = 'object' AND pin ? :old"
    where = (
        f"scope_key = :scope AND jsonb_typeof({doc}) = 'object' "
        f"AND jsonb_typeof({doc} -> 'pins') = 'array' "
        f"AND EXISTS (SELECT 1 FROM jsonb_array_elements({doc} -> 'pins') AS p(pin) "
        f"WHERE {has_old})"
    )
    params = {"scope": FOCUS_SCOPE, "old": old, "new": new}
    bind.execute(
        sa.text(
            f"UPDATE {PREFERENCES} SET value = jsonb_set({doc}, '{{pins}}', ("
            f"SELECT jsonb_agg(CASE WHEN {has_old} "
            "THEN (pin - CAST(:old AS text)) "
            "|| jsonb_build_object(CAST(:new AS text), pin -> CAST(:old AS text)) "
            "ELSE pin END ORDER BY ord) "
            f"FROM jsonb_array_elements({doc} -> 'pins') "
            "WITH ORDINALITY AS t(pin, ord)"
            f"))::json WHERE {where}"
        ),
        params,
    )
    _none_left(bind, PREFERENCES, where, params)


def _filters(bind, old: str, new: str) -> None:
    """Rename the community filter's top-level key."""
    doc = "value::jsonb"
    where = (
        "scope_key = ANY(CAST(:scopes AS text[])) "
        f"AND jsonb_typeof({doc}) = 'object' AND {doc} ? :old"
    )
    params = {"scopes": list(FILTER_SCOPES), "old": old, "new": new}
    bind.execute(
        sa.text(
            f"UPDATE {PREFERENCES} SET value = (({doc} - CAST(:old AS text)) "
            f"|| jsonb_build_object(CAST(:new AS text), {doc} -> CAST(:old AS text)))"
            f"::json WHERE {where}"
        ),
        params,
    )
    _none_left(bind, PREFERENCES, where, params)


def _links(bind, table: str, old: str, new: str, cast: str) -> None:
    """Rewrite the query of a stored notification link."""
    doc = "data::jsonb"
    where = (
        f"data IS NOT NULL AND jsonb_typeof({doc}) = 'object' "
        f"AND strpos({doc} ->> 'smart_link', :old) > 0"
    )
    params = {"old": old, "new": new}
    bind.execute(
        sa.text(
            f"UPDATE {table} SET data = jsonb_set({doc}, '{{smart_link}}', "
            f"to_jsonb(replace({doc} ->> 'smart_link', :old, :new))){cast} "
            f"WHERE {where}"
        ),
        params,
    )
    _none_left(bind, table, where, params)


def _rewrite(bind, names) -> None:
    (pin_old, pin_new), (filter_old, filter_new), (link_old, link_new) = names
    notifications = "public.notifications"
    outbox = "public.notice_outbox"

    def write() -> None:
        _pins(bind, pin_old, pin_new)
        _filters(bind, filter_old, filter_new)
        _links(bind, notifications, link_old, link_new, "::json")
        _links(bind, outbox, link_old, link_new, "")

    _unforced(bind, (PREFERENCES, notifications, outbox), write)


def upgrade() -> None:
    _rewrite(op.get_bind(), FORWARD)


def downgrade() -> None:
    _rewrite(op.get_bind(), BACKWARD)
