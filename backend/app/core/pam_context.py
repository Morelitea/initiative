"""Request-scoped Privileged Access Management (PAM) context.

When a request is served via a live PAM grant (rather than real membership),
the deps layer records the granted guild + access level here. The app-layer
resource access checks (`require_project_access`, `require_document_access`,
`require_queue_access`, `require_counter_group_access`) consult it so that what
a grantee can list under RLS, they can also open/edit — read-only or
read-write per the grant — without an explicit permission row.

A ``contextvars.ContextVar`` keeps this per-request (each request runs in its
own asyncio task with its own context), so there's no cross-request leakage and
the sync access helpers don't need the session threaded through them.
"""

from __future__ import annotations

import contextvars
from typing import Optional, Tuple

# (guild_id, access_level) for the active grant, or None when the request isn't
# served via a grant. access_level is "read" | "read_write".
_active_grant: contextvars.ContextVar[Optional[Tuple[int, str]]] = (
    contextvars.ContextVar("pam_active_grant", default=None)
)


def set_active_grant(guild_id: Optional[int], access_level: Optional[str]) -> None:
    """Record (or clear) the active PAM grant for this request."""
    if guild_id is None or access_level is None:
        _active_grant.set(None)
    else:
        _active_grant.set((guild_id, access_level))


def active_grant_guild() -> Optional[int]:
    """The guild covered by this request's live grant, or None.

    Lets request-time SQL builders (e.g. ``initiative_scope_clause``) embed
    the granted guild as a literal predicate, mirroring how the old
    ``is_initiative_member()`` SQL function honored ``app.pam_*`` GUCs.
    """
    current = _active_grant.get()
    return current[0] if current is not None else None


def active_grant_level(guild_id: int) -> Optional[str]:
    """The grant access level covering ``guild_id`` this request, or None."""
    current = _active_grant.get()
    if current is None:
        return None
    granted_guild, level = current
    return level if granted_guild == guild_id else None


def has_active_grant(guild_id: int) -> bool:
    """Whether this request is served via a live grant covering ``guild_id``.

    Used by list/visibility queries to skip per-membership/permission narrowing
    (a grantee sees all of the guild's content, like a member of every
    initiative) while keeping the explicit guild scope + RLS.
    """
    return active_grant_level(guild_id) is not None


def grant_satisfies(
    guild_id: int, *, access: str = "read", require_owner: bool = False
) -> bool:
    """Whether a live grant covers ``guild_id`` at the requested access level.

    A grant never confers ownership (owner-only operations stay gated on real
    permissions). A read grant satisfies reads only; a read_write grant
    satisfies reads and writes.
    """
    if require_owner:
        return False
    level = active_grant_level(guild_id)
    if level is None:
        return False
    if access == "write":
        return level == "read_write"
    return True
