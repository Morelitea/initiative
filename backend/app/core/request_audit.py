"""Naming each request, measuring it, and recording the privileged ones.

Three jobs, all at the outermost seam so they see every request and its whole
life:

* **Every request gets an id.** It goes on the response as ``X-Request-Id``
  and into the ``context`` block of every audit line the request writes, so a
  line in this stream and a line in the deployment's own logs can be put
  beside each other. Behind a proxy an id that arrived with the request is
  kept, so the name is the same all the way along. A socket is named the same
  way and keeps that name for as long as it is open.
* **Every request is timed and counted** for ``/api/v1/metrics``, by the
  route it matched (the template, not the path typed) and the status it got;
  every open socket is counted while it is open. See :mod:`app.core.metrics`.
* **A request served through a grant is written down.** The guild-access gate
  records the grant on the request's context; when the response is finished
  this writes one ``pam.request`` line saying which grant, which route, and
  what it answered. The grant says somebody was let into a community; these
  say what they did while they were there.

A socket has no response to be finished, so it gets no ``pam.request`` line.
What it has instead is :func:`record_privileged_edit`, which the live editing
socket calls the first time a grantee changes a body — the one thing about a
socket that is worth the same kind of record.

Pure ASGI rather than ``BaseHTTPMiddleware``: it runs on every request, and
this way it costs no extra task and streams pass straight through.
"""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from starlette.datastructures import MutableHeaders

from app.core import audit_context, metrics
from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.services import audit as audit_service

#: The header a request is named by, in and out.
REQUEST_ID_HEADER = "x-request-id"

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


def _header(scope: Scope, name: str) -> str | None:
    """One header's value from a raw ASGI scope."""
    wanted = name.encode("latin-1")
    for key, value in scope.get("headers", ()):
        if key == wanted:
            return value.decode("latin-1", "replace")
    return None


def _incoming_request_id(scope: Scope) -> str | None:
    """The id this request arrived with, where one is taken.

    Only read when the deployment says something it trusts sits in front of
    it: that proxy is what puts a name on a request before this process sees
    it, and on a deployment reached directly there is nothing in front to have
    done so.
    """
    if not settings.BEHIND_PROXY:
        return None
    return audit_context.clean_request_id(_header(scope, REQUEST_ID_HEADER))


def _reached_ids(scope: Scope) -> dict[str, int]:
    """The ids named in the path, and nothing else from it.

    A path also carries slugs and names; the numbers in it are what says which
    community and which thing were reached.
    """
    reached: dict[str, int] = {}
    for name, value in (scope.get("path_params") or {}).items():
        text = str(value)
        if text.isdigit():
            reached[name] = int(text)
    return reached


def _route_template(scope: Scope) -> str | None:
    """The route as it is written, rather than as it was typed; ``None``
    when no route answered."""
    path = getattr(scope.get("route"), "path", None)
    return path if isinstance(path, str) else None


class RequestAuditMiddleware:
    """Open each request's context; close it with a line if it was
    privileged."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope.get("type")
        if kind not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        context, token = audit_context.begin(
            request_id=_incoming_request_id(scope) or audit_context.new_request_id(),
            source_ip=(scope.get("client") or (None,))[0],
            user_agent=_header(scope, "user-agent"),
        )
        if kind == "websocket":
            # Named and carrying its grant for as long as it is open; what it
            # does with that is recorded by the socket itself, since there is
            # no response here to hang a line on.
            metrics.websocket_connections.inc()
            try:
                await self.app(scope, receive, send)
            finally:
                metrics.websocket_connections.dec()
                audit_context.end(token)
            return

        answered: dict[str, int] = {}
        method = metrics.method_label(scope.get("method"))
        in_progress = metrics.http_requests_in_progress.labels(method=method)
        in_progress.inc()
        began = time.perf_counter()

        async def named_send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                answered["status"] = message["status"]
                MutableHeaders(scope=message).setdefault(
                    REQUEST_ID_HEADER, context.request_id
                )
            await send(message)

        try:
            await self.app(scope, receive, named_send)
        finally:
            elapsed = time.perf_counter() - began
            in_progress.dec()
            route = _route_template(scope)
            label = route or metrics.UNMATCHED_ROUTE
            # No response started means the request ended in an exception,
            # which the server answers with a 500.
            status = str(answered.get("status", 500))
            metrics.http_requests.labels(method, label, status).inc()
            metrics.http_request_duration.labels(method, label).observe(elapsed)
            if context.is_privileged:
                audit_service.emit(
                    event_type=AuditEventType.PAM_REQUEST,
                    actor_user_id=context.actor_user_id,
                    guild_id=context.guild_id,
                    detail={
                        "method": scope.get("method"),
                        "route": route or scope.get("path", ""),
                        "status": answered.get("status"),
                        "reached": _reached_ids(scope),
                    },
                )
            audit_context.end(token)


def record_privileged_edit(
    *, guild_id: int, resource_type: str, resource_id: int, actor_user_id: int
) -> bool:
    """Write down that somebody serving a grant changed this body.

    Returns whether a line was written, so the caller can record once per
    session rather than once per keystroke. A socket opened by a member of the
    community writes nothing.
    """
    context = audit_context.current()
    if context is None or not context.is_privileged:
        return False
    audit_service.emit(
        event_type=AuditEventType.PAM_CONTENT_EDITED,
        actor_user_id=actor_user_id,
        guild_id=guild_id,
        target_type=resource_type,
        target_id=resource_id,
    )
    return True
