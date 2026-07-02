"""Test-only harness: route guild-scoped ORM work to the active guild's schema.

In production, ``set_rls_context`` sets ``search_path`` per request from the
guild in the ``/g/{guild_id}`` URL path, so guild-scoped reads/writes land in
``guild_<id>``. Direct-session tests (a factory + a raw session, no HTTP
request) have no such context, so without help their guild-scoped statements
would resolve against ``public`` — where, since the v0.53.5 baseline squash,
the tenant tables **do not exist** on a fresh database.

Two cooperating layers make direct sessions schema-native:

1. **Explicit routing** — ``route_session_to_guild(session, guild_id)`` pins
   the session's ``search_path`` at ``guild_<id>, public``. Every tenant
   factory calls it from its parent object's ``guild_id`` before touching the
   database, so factory reads *and* writes are deterministic regardless of
   flush composition or ordering.
2. **A fail-closed ``before_flush`` net** for raw ``session.add(...)`` in
   tests: a flush that carries guild-scoped rows for exactly one guild is
   routed to that guild's schema; a flush spanning two guilds, or one whose
   tenant rows carry no ``guild_id`` while the session was never routed,
   raises immediately with a pointer here — instead of surfacing later as a
   cryptic ``UndefinedTableError`` from the missing public copy.

Because ``set_config(..., false)`` sets a session-level GUC on the bound
connection, routing persists across commits for the connection-bound test
sessions (see ``conftest.session``). The request path is unaffected: its
sessions route through ``set_rls_context`` before any tenant statement, which
the net recognizes by inspecting the live ``search_path``.
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.db.tenancy import GUILD_SCOPED_TABLES

_installed = False


async def route_session_to_guild(session, guild_id: int) -> None:
    """Pin an AsyncSession's search_path at ``guild_<id>, public``.

    Session-level (survives commits on a connection-bound session). Factories
    call this automatically; call it directly before raw tenant-table reads on
    a session that has not created tenant rows yet.
    """
    gid = int(guild_id)
    conn = await session.connection()
    result = await conn.exec_driver_sql(
        f"SELECT set_config('search_path', 'guild_{gid}, public', false)"
    )
    result.close()


def _tenant_rows(session: Session) -> list:
    return [
        obj
        for obj in (*session.new, *session.dirty, *session.deleted)
        if getattr(obj, "__tablename__", None) in GUILD_SCOPED_TABLES
    ]


def _route_before_flush(session: Session, flush_context, instances) -> None:
    rows = _tenant_rows(session)
    if not rows:
        return
    gids = {
        int(gid) for obj in rows if (gid := getattr(obj, "guild_id", None)) is not None
    }
    if len(gids) > 1:
        raise RuntimeError(
            f"Tenant flush spans multiple guilds {sorted(gids)}; tenant tables "
            "live in per-guild schemas, so one flush can only target one guild. "
            "Commit per guild (see app/testing/schema_harness.py)."
        )
    conn = session.connection()
    if len(gids) == 1:
        gid = next(iter(gids))
        conn.exec_driver_sql(
            f"SELECT set_config('search_path', 'guild_{gid}, public', false)"
        ).close()
        return
    # Tenant rows without a guild_id column (property values, junctions):
    # they must inherit an existing guild route — falling through to public
    # would hit tables that no longer exist there.
    search_path = conn.exec_driver_sql("SHOW search_path").scalar() or ""
    if "guild_" not in search_path:
        names = sorted({type(obj).__name__ for obj in rows})
        raise RuntimeError(
            f"Tenant write for {names} carries no guild_id and the session is "
            "not routed to a guild schema. Use the factories in app.testing, "
            "or call route_session_to_guild(session, guild_id) first "
            "(see app/testing/schema_harness.py)."
        )


def install_guild_routing() -> None:
    """Install the before_flush router once (idempotent)."""
    global _installed
    if not _installed:
        # propagate=True so the listener also fires for SQLModel's Session
        # subclass (the sync session under AsyncSession), not just base Session.
        event.listen(Session, "before_flush", _route_before_flush, propagate=True)
        _installed = True
