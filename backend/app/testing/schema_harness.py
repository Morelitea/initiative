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

Routing is **transaction-local**, mirroring production: the pin lives in
``session.info`` and a ``after_begin`` listener re-applies it at the start of
every transaction (``set_config(..., is_local=true)`` — the same replay
pattern as ``app.db.session._replay_rls_context``), so it survives commits on
the connection-bound test sessions without any session-level connection
state. The request path is unaffected: its sessions route through
``set_rls_context`` before any tenant statement, which the net recognizes by
inspecting the live ``search_path``; a session carrying production rls params
is never pin-replayed (the production hook governs).
"""

from __future__ import annotations

import time

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.db.session import _RLS_ESTABLISHED_INFO_KEY, _RLS_PARAMS_INFO_KEY
from app.db.tenancy import GUILD_SCOPED_TABLES

_installed = False

_PIN_INFO_KEY = "guild_search_path_pin"
_PIN_STAMP_KEY = "guild_search_path_pin_at"


def _record_pin(session, search_path: str) -> None:
    session.info[_PIN_INFO_KEY] = search_path
    session.info[_PIN_STAMP_KEY] = time.monotonic()


def _pin_sql(search_path: str) -> str:
    # search_path is always built from int(guild_id) — injection-safe.
    return f"SELECT set_config('search_path', '{search_path}', true)"


async def route_session_to_guild(session, guild_id: int) -> None:
    """Pin an AsyncSession's search_path at ``guild_<id>, public``.

    Transaction-local + replayed per transaction (survives commits on a
    connection-bound session via the after_begin listener). Factories call
    this automatically; call it directly before raw tenant-table reads on a
    session that has not created tenant rows yet.
    """
    gid = int(guild_id)
    sp = f"guild_{gid}, public"
    _record_pin(session, sp)
    conn = await session.connection()
    result = await conn.exec_driver_sql(_pin_sql(sp))
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
        sp = f"guild_{gid}, public"
        # Record the pin so the after_begin listener re-routes the NEXT
        # transaction too (a factory that commits then reads back).
        _record_pin(session, sp)
        conn.exec_driver_sql(_pin_sql(sp)).close()
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


def _replay_search_path_pin(session: Session, transaction, connection) -> None:
    """after_begin: re-apply the harness pin on each new transaction.

    Mirrors the old session-level semantics: the MOST RECENT routing intent
    wins. A test session can interleave ``set_rls_context`` calls (service
    code under test) with factory pins; whichever was applied last governs
    the next transaction. This listener registers after the production
    replay hook, so when the pin is newer it overrides the replayed
    search_path (role/GUCs from the params still stand — the pin only
    routes, exactly like the session-level pin it replaces).
    """
    if transaction.nested:
        return
    pin = session.info.get(_PIN_INFO_KEY)
    if not pin:
        return
    if session.info.get(_RLS_PARAMS_INFO_KEY) is not None:
        params_at = session.info.get(_RLS_ESTABLISHED_INFO_KEY, 0.0)
        if params_at >= session.info.get(_PIN_STAMP_KEY, 0.0):
            return  # production context is the newer routing intent
    connection.exec_driver_sql(_pin_sql(pin)).close()


def install_guild_routing() -> None:
    """Install the before_flush router + pin replay once (idempotent)."""
    global _installed
    if not _installed:
        # propagate=True so the listeners also fire for SQLModel's Session
        # subclass (the sync session under AsyncSession), not just base Session.
        event.listen(Session, "before_flush", _route_before_flush, propagate=True)
        event.listen(Session, "after_begin", _replay_search_path_pin, propagate=True)
        _installed = True
