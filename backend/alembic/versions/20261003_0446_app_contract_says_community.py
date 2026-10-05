"""app contract says community

Apps and their manifests name a community as a community, so the values stored
from them do too: a surface's ``guild`` placement, the ``guild:admin`` scope
(asked for by a service, granted to an install, and kept as a registration's
ceiling), and a service app's ``guild_summary`` key. Each is rewritten in the
installed definitions and grants of every community, and in the published
listing versions and registrations.

Revision ID: 20261003_0446
Revises: 20261003_0445
Create Date: 2026-10-03
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261003_0446"
down_revision = "20261003_0445"
branch_labels = None
depends_on = None

#: ``(old, new)`` for a surface's placement, the standing scope, and the
#: summary key, in that order.
FORWARD = (
    ("guild", "community"),
    ("guild:admin", "community:admin"),
    ("guild_summary", "community_summary"),
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


def _none_left(bind, table: str, where: str, params: dict[str, str]) -> None:
    left = bind.execute(
        sa.text(f"SELECT count(*) FROM {table} WHERE {where}"), params
    ).scalar()
    if left:
        raise RuntimeError(f"{left} rows of {table} still match {where}")


def _scopes(bind, table: str, column: str, scope: tuple[str, str]) -> None:
    """Replace one scope in a text array."""
    old, new = scope
    where = f"CAST(:old AS text) = ANY({column})"
    bind.execute(
        sa.text(
            f"UPDATE {table} SET {column} = "
            f"array_replace({column}, CAST(:old AS text), CAST(:new AS text)) "
            f"WHERE {where}"
        ),
        {"old": old, "new": new},
    )
    _none_left(bind, table, where, {"old": old})


def _holding(array: str, path: str) -> str:
    """Whether ``definition`` holds ``:old`` in an array at ``path``, below the
    array the update walks (``array``)."""
    return (
        f"jsonb_typeof(definition #> '{array}') = 'array' AND "
        f"jsonb_path_exists(definition, '{path}[*] ? (@ == $v)', "
        "jsonb_build_object('v', CAST(:old AS text)))"
    )


def _replaced(array: str) -> str:
    """``array``, a JSON array, with ``:old`` replaced by ``:new`` in place."""
    return (
        "COALESCE((SELECT jsonb_agg(CASE WHEN s = to_jsonb(CAST(:old AS text)) "
        "THEN to_jsonb(CAST(:new AS text)) ELSE s END ORDER BY o) "
        f"FROM jsonb_array_elements({array}) WITH ORDINALITY AS x(s, o)), "
        "'[]'::jsonb)"
    )


def _definitions(bind, table: str, names) -> None:
    """Rewrite the stored definitions in ``table``."""
    surface, scope, summary = names

    old, new = surface
    where = _holding("{embeds}", "$.embeds[*].scopes")
    placements = _replaced("e -> 'scopes'")
    bind.execute(
        sa.text(
            f"UPDATE {table} SET definition = jsonb_set(definition, '{{embeds}}', "
            "(SELECT jsonb_agg(CASE WHEN jsonb_typeof(e -> 'scopes') = 'array' "
            f"THEN jsonb_set(e, '{{scopes}}', {placements}) "
            "ELSE e END ORDER BY i) "
            "FROM jsonb_array_elements(definition -> 'embeds') "
            f"WITH ORDINALITY AS y(e, i))) WHERE {where}"
        ),
        {"old": old, "new": new},
    )
    _none_left(bind, table, where, {"old": old})

    old, new = scope
    where = _holding("{service,scopes}", "$.service.scopes")
    asked = _replaced("definition #> '{service,scopes}'")
    bind.execute(
        sa.text(
            f"UPDATE {table} SET definition = jsonb_set(definition, "
            f"'{{service,scopes}}', {asked}) "
            f"WHERE {where}"
        ),
        {"old": old, "new": new},
    )
    _none_left(bind, table, where, {"old": old})

    old, new = summary
    bind.execute(
        sa.text(
            f"UPDATE {table} SET definition = (definition - '{old}') || "
            f"jsonb_build_object('{new}', definition -> '{old}') "
            f"WHERE definition ? '{old}'"
        )
    )
    _none_left(bind, table, f"definition ? '{old}'", {})


def _public(bind, names) -> None:
    versions = "public.marketplace_listing_versions"
    registrations = "public.app_service_registrations"

    def write() -> None:
        _definitions(bind, versions, names)
        _scopes(bind, registrations, "scope_ceiling", names[1])

    _unforced(bind, (versions, registrations), write)


def _guild(bind, names) -> None:
    def write() -> None:
        _definitions(bind, "guild_apps", names)
        _scopes(bind, "guild_apps", "granted_scopes", names[1])

    _unforced(bind, ("guild_apps",), write)


def upgrade() -> None:
    bind = op.get_bind()
    _public(bind, FORWARD)
    run_for_each_guild_schema(bind, lambda: _guild(bind, FORWARD))


def downgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, lambda: _guild(bind, BACKWARD))
    _public(bind, BACKWARD)
