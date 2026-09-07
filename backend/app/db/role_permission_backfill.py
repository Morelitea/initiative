"""Fill in the role permission rows a tool that shipped late never wrote.

An initiative role stores one ``initiative_role_permissions`` row per
permission key, written when the role is created. A tool added afterwards adds
two keys — ``{plural}_enabled`` and ``create_{plural}`` — to every role created
from then on, and to none of the roles that already existed. The absence reads
as the default at runtime (``DEFAULT_PERMISSION_VALUES``), so nothing is
mis-authorized; what drifts is the *stored* role against the role the code
describes, which is what a settings screen shows and what an operator reasons
about.

This module owns the one statement that closes that gap, so a migration adding
a tool can call it in a line instead of restating the join. It is deliberately
parameterised by the key/default pairs rather than reading the live ``Tool``
enum: a migration records what was true at its revision, and a later tool must
be a later migration.
"""

from __future__ import annotations

import re

from alembic import op

_TABLE = "initiative_role_permissions"

# A permission key is a bare identifier. The values reach the statement as
# literals, so they are checked against that shape before they get there.
_PERMISSION_KEY = re.compile(r"^[a-z][a-z0-9_]*$")


def role_permission_backfill_sql(defaults: dict[str, bool]) -> str:
    """The INSERT that writes the missing rows, unqualified so it runs in
    whichever guild schema the caller's ``search_path`` names.

    ``defaults`` maps each permission key to the value a role created today
    would store. The built-in ``project_manager`` role is the one exception —
    it is defined as every permission on — so it is backfilled ``true``
    regardless of the mapping. Existing rows are never touched: an operator who
    turned a permission off keeps it off.

    Split out from :func:`backfill_role_permissions` so the statement can be
    exercised against a real schema without an Alembic context.
    """
    invalid = sorted(key for key in defaults if not _PERMISSION_KEY.match(key))
    if invalid:
        raise ValueError(f"not permission keys: {invalid}")

    values = ", ".join(
        f"('{key}', {'true' if enabled else 'false'})"
        for key, enabled in sorted(defaults.items())
    )
    return f"""
        INSERT INTO {_TABLE} (initiative_role_id, permission_key, enabled)
        SELECT r.id,
               k.permission_key,
               CASE
                   WHEN r.is_builtin AND r.name = 'project_manager' THEN true
                   ELSE k.enabled
               END
        FROM initiative_roles AS r
        CROSS JOIN (VALUES {values}) AS k(permission_key, enabled)
        ON CONFLICT (initiative_role_id, permission_key) DO NOTHING
    """


def backfill_role_permissions(defaults: dict[str, bool]) -> None:
    """Run the backfill in the current schema, from a migration.

    Wraps :func:`role_permission_backfill_sql` in the row-level-security
    lift the write needs.
    """
    if not defaults:
        return

    # FORCE ROW LEVEL SECURITY binds the table's owner, which is the role every
    # migration runs as, and the policies key on request GUCs a migration has
    # no value for. Lift it for the write and put it back either way.
    op.execute(f"ALTER TABLE {_TABLE} NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(role_permission_backfill_sql(defaults))
    finally:
        op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
