"""Proof that a state-changing request was intended, for cookie sessions.

The session cookie authenticates every API route -- ``get_current_user`` falls
back to it when no ``Authorization`` header is present (``deps.py``), so it is
not merely a refresh credential. It is ``SameSite=Lax`` on path ``/``, and that
attribute was the entire defence against a cross-site write.

Lax is a good defence and is not a complete one. It is one browser default,
with nothing that fails loudly if the attribute is dropped, and nothing at all
in a client that does not honour it. CORS does not close the gap either: a
cross-site ``<form enctype="multipart/form-data">`` is a simple request, sends
no preflight, and this API has multipart routes that write
(``galleries.py:877``, ``documents.py:953``, the avatar upload). The browser
attaches the cookie and the server has already decided who the caller is.

So this adds a second, independent layer: on an unsafe method authenticated by
the COOKIE, the request must also prove it came from an origin we serve. A
cross-site form cannot do that -- it cannot set ``Origin``, and it cannot stop
the browser from sending the real one.

What is deliberately NOT here:

* **Nothing for header-authenticated callers.** An ``Authorization`` header is
  not attached by a browser on a cross-site request, so bearer tokens, API keys
  and device tokens were never exposed to this and are not asked for anything.
  That is also what keeps mobile shells and API scripts working unchanged.
* **No token to mint, store or rotate.** A synchroniser or double-submit token
  is a stronger primitive and can be layered on top of this later. It also
  needs every client that writes to carry it, which is a change across the
  whole frontend; this is backend-only and effective immediately. Doing the
  cheap layer first is not an argument against the expensive one.
* **No trust in ``Sec-Fetch-Site: same-site``.** Same-site includes sibling
  subdomains, and a carelessly added subdomain is one of the ways this threat
  was described as failing. Only ``same-origin`` is taken as proof on its own.
"""

from __future__ import annotations


from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.core.security import SESSION_COOKIE_NAME

#: Methods that cannot change state, per RFC 9110. HEAD and OPTIONS included:
#: OPTIONS is the CORS preflight and must never be answered with a 403 from
#: here, or the preflight failure hides whatever the real request would have
#: said.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

#: Machine-readable, so a client can tell this apart from an authorization
#: failure and not send the user to log in again over it.
CSRF_ERROR_CODE = "CSRF_ORIGIN_REQUIRED"


def _carries_session_cookie(headers: Headers) -> bool:
    """Whether this request is authenticated by the cookie rather than a header.

    An ``Authorization`` header wins in ``get_current_user``, so a request that
    has one is not a cookie session even if a cookie also rode along -- and it
    is not reachable cross-site in the first place.
    """
    if headers.get("authorization"):
        return False
    cookie = headers.get("cookie")
    if not cookie:
        return False
    # Substring is not enough: a cookie named `x_session_token` would contain
    # `session_token`. Split on the separator the header actually uses.
    return any(
        piece.strip().split("=", 1)[0] == SESSION_COOKIE_NAME
        for piece in cookie.split(";")
    )


def intent_is_proven(headers: Headers) -> bool:
    """Whether the request shows it came from somewhere we serve.

    ``Sec-Fetch-Site: same-origin`` is conclusive on its own and is checked
    first, because a same-origin fetch is the common case and needs no
    allowlist lookup. Otherwise the ``Origin`` must be one this deployment
    serves -- which covers a split-origin deployment, where the SPA is hosted
    somewhere other than the API, without weakening anything: that list is the
    same one CORS already credentials.

    A request with neither header is refused. Every browser sends ``Origin`` on
    an unsafe method; something presenting a session cookie without one is not
    a browser doing what browsers do.
    """
    if headers.get("sec-fetch-site") == "same-origin":
        return True
    origin = headers.get("origin")
    if origin is None:
        return False
    return origin in settings.cors_origins


class CsrfOriginMiddleware:
    """Refuse a cookie-authenticated write that cannot say where it came from.

    Pure ASGI rather than ``BaseHTTPMiddleware``: this decides from headers
    alone and must answer before the body is read, so there is no reason to
    buffer a request that is about to be refused.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        if not _carries_session_cookie(headers) or intent_is_proven(headers):
            await self.app(scope, receive, send)
            return

        response = JSONResponse(
            status_code=403,
            content={
                "detail": (
                    "This request was not sent from a page this server serves. "
                    "If you are using an API client, authenticate with an "
                    "Authorization header rather than a session cookie."
                ),
                "code": CSRF_ERROR_CODE,
            },
        )
        await response(scope, receive, send)
