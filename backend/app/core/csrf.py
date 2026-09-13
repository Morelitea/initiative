"""Where a state-changing request came from, for cookie-authenticated callers.

The session cookie authenticates ordinary API requests, not only the refresh
route: ``get_current_user`` falls back to it when no ``Authorization`` header
is present. So for those callers this asks for one more thing before an unsafe
method is allowed through -- that the request came from a page this deployment
serves.

Scope, and why it is drawn here:

* **Only cookie-authenticated callers.** An ``Authorization`` header is never
  attached by a browser on someone else's behalf, so bearer tokens, API keys
  and device tokens are not asked for anything. That is also what keeps mobile
  shells and API scripts working unchanged.
* **Unsafe methods, and every WebSocket handshake.** ``OPTIONS`` is excluded
  along with the read methods: it is the CORS preflight and is answered before
  this runs. A handshake has no method to branch on and opens a two-way
  channel, so it is treated as state-changing.
* **No token to mint, store or rotate.** A synchroniser or double-submit token
  is a stronger primitive and can be added on top of this later. It also needs
  every client that writes to carry it, which is a change across the whole
  frontend; this is backend-only.
* **``Sec-Fetch-Site: same-site`` is not accepted on its own**, because it
  includes sibling subdomains. Only ``same-origin`` is conclusive by itself;
  anything else is matched against the same origin allowlist CORS uses.

Detail beyond what the code does lives in the private tracker, per
CLAUDE.md "Security-sensitive comments".
"""

from __future__ import annotations


from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.core.messages import AuthMessages
from app.core.security import SESSION_COOKIE_NAME

#: Methods that cannot change state, per RFC 9110.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

#: Kept as a name so callers can refer to the code without repeating it.
CSRF_ERROR_CODE = AuthMessages.REQUEST_ORIGIN_NOT_RECOGNIZED


def _carries_session_cookie(headers: Headers) -> bool:
    """Whether this request is authenticated by the cookie rather than a header.

    An ``Authorization`` header wins in ``get_current_user``, so a request that
    carries one is not a cookie session even if a cookie rode along too.
    """
    if headers.get("authorization"):
        return False
    cookie = headers.get("cookie")
    if not cookie:
        return False
    # Compare whole names: a cookie called `x_session_token` contains the
    # session cookie's name as a substring without being it.
    return any(
        piece.strip().split("=", 1)[0] == SESSION_COOKIE_NAME
        for piece in cookie.split(";")
    )


def intent_is_proven(headers: Headers) -> bool:
    """Whether the request came from a page this deployment serves.

    ``Sec-Fetch-Site: same-origin`` is conclusive on its own and is checked
    first, because a same-origin fetch is the common case and needs no
    allowlist lookup. Otherwise the ``Origin`` must be one this deployment
    serves, which is how a split-origin deployment -- SPA hosted somewhere
    other than the API -- still works. That list is the one CORS already
    credentials, so the two cannot drift apart.

    Neither header present means the answer is no. Browsers send ``Origin`` on
    an unsafe method as a matter of course.
    """
    if headers.get("sec-fetch-site") == "same-origin":
        return True
    origin = headers.get("origin")
    if origin is None:
        return False
    return origin in settings.cors_origins


class CsrfOriginMiddleware:
    """Refuse a cookie-authenticated write that cannot say where it came from.

    Pure ASGI rather than ``BaseHTTPMiddleware``: the decision is made from
    headers alone, so there is no reason to buffer a body that is not going to
    be used.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await self._websocket(scope, receive, send)
            return

        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        if not _carries_session_cookie(headers) or intent_is_proven(headers):
            await self.app(scope, receive, send)
            return

        # A machine-readable code, mapped to text in
        # frontend/public/locales/*/errors.json, per CLAUDE.md "Backend: Error
        # code constants".
        response = JSONResponse(status_code=403, content={"detail": CSRF_ERROR_CODE})
        await response(scope, receive, send)

    async def _websocket(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Apply the same rule to a handshake.

        A WebSocket carries the session cookie like any other request and is not
        bound by the same-origin policy, and the routes here fall back to that
        cookie when the first message supplies no token. There is no method to
        branch on -- a handshake is always the start of a two-way channel, so it
        is treated as state-changing.

        Refused before the route sees it, by closing in response to the connect
        rather than accepting first: a channel that is accepted and then closed
        has already run whatever the route does on accept.
        """
        headers = Headers(scope=scope)
        if not _carries_session_cookie(headers) or intent_is_proven(headers):
            await self.app(scope, receive, send)
            return

        # Drain the connect so the close is a valid reply to it.
        message = await receive()
        if message["type"] != "websocket.connect":  # pragma: no cover - spec order
            return
        # 1008 policy violation, which is what the routes here already use for a
        # handshake they refuse.
        await send({"type": "websocket.close", "code": 1008})
