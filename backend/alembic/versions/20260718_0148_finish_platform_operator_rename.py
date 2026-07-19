"""Finish the platform ``admin`` -> ``operator`` rename when 0139 no-opped.

Migration 20260710_0139 renames the cluster-global role ``platform_admin`` to
``platform_operator`` only while the target name is still free. Roles are
cluster-global but databases are not: when a database is (re)created in a
cluster where the rename already happened — a rebuilt test database, or a
restore into an existing cluster — the frozen baseline re-creates
``platform_admin`` from its frozen tier list and binds three policies to it
(``access_grants_admin``, ``users_platform_manage``, ``users_platform_read``),
and 0139's guarded rename then finds ``platform_operator`` already taken and
does nothing. That database is left with those policies bound to a role no
request ever assumes, so operator/owner platform reads fail closed (admins see
only their own rows).

This migration converges either state at apply time:

* old role exists, target free -> plain ``ALTER ROLE ... RENAME`` (as 0139);
* both roles exist -> re-bind every policy in THIS database that names the old
  role onto the new one, then drop the old role unless something elsewhere in
  the cluster still depends on it (that database's own upgrade finishes it).

A database whose policies already bind ``platform_operator`` is untouched, so
re-running is a no-op.

Revision ID: 20260718_0148
Revises: 20260718_0147
Create Date: 2026-07-18
"""

from __future__ import annotations

import string

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "20260718_0148"
down_revision = "20260718_0147"
branch_labels = None
depends_on = None


# Prefix defense-in-depth (operator/test config, never user input): an explicit
# allow-list of role-name characters so a stray quote can't break out of DDL.
# Frozen copy of the baseline helper — migrations are immutable records and must
# not drift if the prefix logic ever changes.
_ALLOWED_IDENT_CHARS = frozenset(string.ascii_letters + string.digits + "_")


def _platform_prefix() -> str:
    """The platform-role prefix, read from settings at APPLY time (the test
    suite sets it before running migrations; empty in prod/dev)."""
    from app.core.config import settings

    prefix = settings.PLATFORM_ROLE_PREFIX
    if not set(prefix) <= _ALLOWED_IDENT_CHARS:
        raise ValueError(f"unsafe PLATFORM_ROLE_PREFIX for role DDL: {prefix!r}")
    return prefix


def _safe_ident(name: str) -> str:
    """Guard an identifier before it lands in an f-string DDL sink. Everything
    this migration renders comes from the catalog or hardcoded literals, held
    to the same allow-list as the prefix."""
    if not name or not set(name) <= _ALLOWED_IDENT_CHARS:
        raise ValueError(f"unsafe identifier for DDL: {name!r}")
    return name


def upgrade() -> None:
    connection = op.get_bind()
    prefix = _platform_prefix()
    old = f"{prefix}platform_admin"
    new = f"{prefix}platform_operator"

    old_oid = connection.execute(
        text("SELECT oid FROM pg_roles WHERE rolname = :r"), {"r": old}
    ).scalar()
    if old_oid is None:
        return

    new_exists = connection.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": new}
    ).scalar()
    if not new_exists:
        # 0139 never ran against this cluster state; the plain rename still
        # works and carries every grant and policy binding with it.
        connection.execute(
            text(f'ALTER ROLE "{_safe_ident(old)}" RENAME TO "{_safe_ident(new)}"')
        )
        return

    # Both roles exist: re-point this database's policies at the operator role.
    # OID 0 in polroles is the PUBLIC pseudo-role (no pg_roles row), so it is
    # carried as a separate flag and re-emitted as the keyword — resolving names
    # alone would silently drop it from the rebound TO list.
    bindings = connection.execute(
        text(
            "SELECT n.nspname AS sch, c.relname AS tbl, p.polname AS pol, "
            "0 = ANY(p.polroles) AS has_public, "
            "ARRAY(SELECT r.rolname FROM pg_roles r "
            "      WHERE r.oid = ANY(p.polroles)) AS roles "
            "FROM pg_policy p "
            "JOIN pg_class c ON c.oid = p.polrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE :oid = ANY(p.polroles)"
        ),
        {"oid": old_oid},
    ).all()
    for sch, tbl, pol, has_public, roles in bindings:
        rebound: list[str] = []
        for role in roles:
            target = new if role == old else role
            if target not in rebound:
                rebound.append(target)
        parts = [f'"{_safe_ident(r)}"' for r in rebound]
        if has_public:
            parts.append("PUBLIC")
        to_clause = ", ".join(parts)
        connection.execute(
            text(
                f'ALTER POLICY "{_safe_ident(pol)}" '
                f'ON "{_safe_ident(sch)}"."{_safe_ident(tbl)}" TO {to_clause}'
            )
        )

    # The old role should now be unreferenced; drop it so the ladder has one
    # role per tier again. Another database in the same cluster may still bind
    # policies to it — leave it for that database's own upgrade in that case.
    connection.execute(
        text(
            f"""
            DO $$ BEGIN
                BEGIN
                    DROP ROLE "{_safe_ident(old)}";
                EXCEPTION WHEN dependent_objects_still_exist THEN
                    NULL;
                END;
            END $$;
            """
        )
    )


def downgrade() -> None:
    # Convergence repair only — there is no meaningful prior state to restore.
    # Reverting the rename itself is 20260710_0139's downgrade.
    pass
