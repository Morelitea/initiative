"""Request-scoped active-guild role context.

The deps layer records the authenticated user's role in the request's active
guild here (mirroring ``pam_context``). The sync app-layer access checks
(``require_project_access`` / ``require_document_access``) consult it for the
guild-admin leg of the initiative-scope gate — the leg the old RESTRICTIVE RLS
policies expressed as ``current_setting('app.current_guild_role') = 'admin'`` —
without the session being threaded through them.

Keyed by guild id so a context recorded for the request's active guild never
bleeds into another guild's entities during cross-guild gathers. PAM requests
deliberately leave this unset — grant semantics flow through ``pam_context``.
"""

from __future__ import annotations

import contextvars
from typing import Optional, Tuple

# (guild_id, role) for the request's active guild membership, or None.
_active_role: contextvars.ContextVar[Optional[Tuple[int, str]]] = (
    contextvars.ContextVar("active_guild_role", default=None)
)


def set_active_role(guild_id: Optional[int], role: Optional[str]) -> None:
    """Record (or clear) the active guild membership role for this request."""
    if guild_id is None or role is None:
        _active_role.set(None)
    else:
        _active_role.set((guild_id, role))


def active_guild_role(guild_id: Optional[int]) -> Optional[str]:
    """The recorded role if it covers ``guild_id`` this request, else None."""
    if guild_id is None:
        return None
    current = _active_role.get()
    if current is None:
        return None
    recorded_guild, role = current
    return role if recorded_guild == guild_id else None
