"""Test-only harness: route guild-scoped ORM writes to the active guild's schema.

In production, ``set_rls_context`` sets ``search_path`` per request from the
guild in the ``/g/{guild_id}`` URL path, so guild-scoped reads/writes land in
``guild_<id>``.
Direct-session tests (a factory + a raw session, no HTTP request) have no such
context, so without help their guild-scoped writes would land in ``public``.

This installs a single ``before_flush`` listener on the ORM ``Session``: when a
flush carries guild-scoped rows for exactly one guild, it points ``search_path``
at that guild's schema before the flush SQL runs. Because ``set_config`` sets a
session-level GUC, the routing persists to subsequent reads too — so a test that
writes then reads the same guild sees its rows. Tables without a ``guild_id``
column (property values, junctions) inherit the ``search_path`` already set by
the parent write in the same guild.

Pair this with provision-on-create in the ``create_guild`` factory so the schema
exists; an unprovisioned guild's schema is simply skipped by ``search_path`` and
falls through to ``public`` (no error).
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.db.tenancy import GUILD_SCOPED_TABLES

_installed = False


def _flush_guild_ids(session: Session) -> set[int]:
    gids: set[int] = set()
    for obj in (*session.new, *session.dirty, *session.deleted):
        if getattr(obj, "__tablename__", None) in GUILD_SCOPED_TABLES:
            gid = getattr(obj, "guild_id", None)
            if gid is not None:
                gids.add(int(gid))
    return gids


def _route_before_flush(session: Session, flush_context, instances) -> None:
    gids = _flush_guild_ids(session)
    # Only route when the flush is unambiguously about a single guild. A flush
    # spanning multiple guilds (rare in tests) keeps whatever search_path is set.
    if len(gids) == 1:
        gid = next(iter(gids))
        session.connection().exec_driver_sql(
            f"SELECT set_config('search_path', 'guild_{gid}, public', false)"
        )


def install_guild_routing() -> None:
    """Install the before_flush router once (idempotent)."""
    global _installed
    if not _installed:
        # propagate=True so the listener also fires for SQLModel's Session
        # subclass (the sync session under AsyncSession), not just base Session.
        event.listen(Session, "before_flush", _route_before_flush, propagate=True)
        _installed = True
