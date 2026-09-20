"""What the log knows about the request a line came from.

Every audit line carries a ``context`` block: the id this request is known by,
where it arrived from, and — when the caller reached a community through a
privileged-access grant rather than membership — which grant let them in. The
id is the thread back to the deployment's own logs, which record the same
request under the same name.

The value is a **mutable holder** in a ``contextvars.ContextVar``. The
middleware that opens a request puts one there; the guild-access gate fills in
the grant half when it establishes one, and a request that used a grant keeps
saying so; ``services.audit.record`` copies it into the envelope. A holder
rather than a value per write, so what the gate adds reaches the middleware
that opened the request whichever task each of them runs in.

Outside a request — a background sweep, a startup seed — there is no holder,
and a line written there carries ``"context": null``.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import Any, Optional
from uuid import uuid4

#: The longest client-supplied value that reaches a line. A user agent is
#: whatever the caller typed into it, and a log line is not the place to keep
#: all of it.
MAX_USER_AGENT = 256

#: What a request id may be made of, for one arriving from a proxy. Letters,
#: digits and the three separators the common formats use.
_ID_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
)
MAX_REQUEST_ID = 128


@dataclass
class RequestContext:
    """One request's own details, filled in as they become known."""

    request_id: str
    source_ip: Optional[str] = None
    user_agent: Optional[str] = None
    #: The account the request is being served as, once it has authenticated.
    actor_user_id: Optional[int] = None
    #: The community a grant reaches, and the grant that reaches it.
    guild_id: Optional[int] = None
    grant_id: Optional[int] = None
    access_level: Optional[str] = None
    settings_grant_id: Optional[int] = None
    settings_level: Optional[str] = None
    #: Whether the grant was issued and approved by the same account, which is
    #: what breaking glass does.
    break_glass: Optional[bool] = None

    @property
    def is_privileged(self) -> bool:
        """Whether this request is being served by a grant rather than by
        membership."""
        return self.grant_id is not None or self.settings_grant_id is not None

    def as_envelope(self) -> dict[str, Any]:
        """The ``context`` block, with the grant half present only when there
        is a grant."""
        block: dict[str, Any] = {
            "request_id": self.request_id,
            "source_ip": self.source_ip,
            "user_agent": self.user_agent,
        }
        if self.is_privileged:
            block.update(
                {
                    "grant_id": self.grant_id,
                    "access_level": self.access_level,
                    "settings_grant_id": self.settings_grant_id,
                    "settings_level": self.settings_level,
                    "break_glass": self.break_glass,
                }
            )
        return block


_request: contextvars.ContextVar[Optional[RequestContext]] = contextvars.ContextVar(
    "audit_request_context", default=None
)


def new_request_id() -> str:
    """A fresh id for a request that arrived without one."""
    return uuid4().hex


def clean_request_id(supplied: Optional[str]) -> Optional[str]:
    """``supplied`` if it is a plausible request id, else ``None``.

    An id arrives from a proxy and reaches a log line, so it is held to a
    length and a character set rather than passed through as typed.
    """
    if not supplied or len(supplied) > MAX_REQUEST_ID:
        return None
    return supplied if all(char in _ID_CHARS for char in supplied) else None


def begin(
    *,
    request_id: str,
    source_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> tuple[RequestContext, contextvars.Token]:
    """Open a request's context and return it with the token that closes it."""
    context = RequestContext(
        request_id=request_id,
        source_ip=source_ip,
        user_agent=(user_agent or None) and user_agent[:MAX_USER_AGENT],
    )
    return context, _request.set(context)


def end(token: contextvars.Token) -> None:
    """Close the request opened with ``token``."""
    _request.reset(token)


def current() -> Optional[RequestContext]:
    """This request's context, or ``None`` outside a request."""
    return _request.get()


def note_grant(
    *,
    actor_user_id: Optional[int],
    guild_id: int,
    grant_id: Optional[int] = None,
    access_level: Optional[str] = None,
    settings_grant_id: Optional[int] = None,
    settings_level: Optional[str] = None,
    break_glass: Optional[bool] = None,
) -> None:
    """Record that this request reaches ``guild_id`` through a grant.

    The first grant noted is the one kept. A request establishes its own
    context before anything else runs, so the first is what admitted it; what
    a later excursion into some other community routes as does not change
    what let this request in.
    """
    context = _request.get()
    if context is None or context.is_privileged:
        return
    context.actor_user_id = actor_user_id
    context.guild_id = guild_id
    context.grant_id = grant_id
    context.access_level = access_level
    context.settings_grant_id = settings_grant_id
    context.settings_level = settings_level
    context.break_glass = break_glass


def envelope_context() -> Optional[dict[str, Any]]:
    """The ``context`` block for a line written now, or ``None``."""
    context = _request.get()
    return context.as_envelope() if context is not None else None
