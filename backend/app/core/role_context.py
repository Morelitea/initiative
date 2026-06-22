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
from typing import FrozenSet, Optional, Tuple

# (guild_id, role) for the request's active guild membership, or None.
_active_role: contextvars.ContextVar[Optional[Tuple[int, str]]] = (
    contextvars.ContextVar("active_guild_role", default=None)
)

# Initiative ids (in the request's active guild) where the user holds a role with
# "Full access" (``override_share_restrictions``). The initiative-scoped sibling
# of the guild-admin override: the sync DAC checks consult this so a full-access
# PM bypasses gate 4 (sharing) for those initiatives' resources. Precomputed once
# per request (set alongside the active role) so the sync checks stay sync.
_override_initiatives: contextvars.ContextVar[FrozenSet[int]] = contextvars.ContextVar(
    "override_share_initiatives", default=frozenset()
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


def set_override_sharing_initiatives(initiative_ids: Optional[FrozenSet[int]]) -> None:
    """Record (or clear) the initiatives where the user has "Full access" this
    request. Set alongside :func:`set_active_role`; cleared (empty) for PAM /
    break-glass / no-context paths."""
    _override_initiatives.set(
        frozenset(initiative_ids) if initiative_ids else frozenset()
    )


def request_overrides_sharing(initiative_id: Optional[int]) -> bool:
    """Whether the request holds "Full access" in ``initiative_id`` — the
    initiative-scoped sibling of ``is_request_guild_admin``. Reads the per-request
    set populated at guild-session establishment (initiative ids are globally
    unique, so the set need not be keyed by guild)."""
    if initiative_id is None:
        return False
    return initiative_id in _override_initiatives.get()
