"""The community a request's session is routed into.

A guild schema is what says which community a row belongs to, so a row carries
no column naming it. What still has to name one is a **payload**: a cross-guild
list hands a reader rows from several communities, and the link it builds has to
go back to the right one.

The answer is the routing decision itself, recorded here by
:func:`app.db.session.set_rls_context` — the one seam every routed session
passes through, which also writes ``app.current_guild_id`` for the database.
Reading it back means the community a response reports and the schema its rows
came from are one fact rather than two that can disagree.

It is set whenever a guild row is readable at all: without ``set_rls_context``
the login role cannot reach a guild schema, so there is no row to serialize. A
grant reaches its community through ``pam_guild_id`` and a settings grant
through ``settings_guild_id``; all three name the community being read, so all
three are recorded here.

Scoped to the async task, like the other request contextvars, so one guild's
value never reaches another's rows — a cross-guild gather re-routes per
community and this follows.
"""

from __future__ import annotations

import contextvars
from typing import Optional

_routed_guild: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "routed_guild_id", default=None
)


def set_routed_guild_id(guild_id: Optional[int]) -> None:
    """Record (or clear) the community this session is routed into."""
    _routed_guild.set(guild_id)


def routed_guild_id() -> Optional[int]:
    """The community this session is routed into, or None if it is not."""
    return _routed_guild.get()


def require_routed_guild_id() -> int:
    """The community this session is routed into.

    For a payload whose ``guild_id`` is required: a serializer runs inside the
    routed session that read its rows, so there is one. Raising beats reporting
    a community nobody routed into.
    """
    guild_id = _routed_guild.get()
    if guild_id is None:
        raise RuntimeError(
            "no community is routed on this session; set_rls_context must run "
            "before guild content is serialized"
        )
    return guild_id
