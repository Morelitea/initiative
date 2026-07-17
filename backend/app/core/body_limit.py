"""ASGI body-size enforcement for bounded-upload routes.

A handler-level ``Content-Length`` check is too late: FastAPI resolves the
request body (and parses JSON) before any handler code runs, and a chunked
request carries no ``Content-Length`` at all. This middleware enforces the
bound at the transport seam instead — the declared length is rejected before
a byte is read, and a chunked/lying stream is cut off the moment it exceeds
the limit, so no more than ``limit`` bytes are ever buffered.

Pure ASGI (not ``BaseHTTPMiddleware``): it must wrap ``receive`` itself.
Limits are resolved per request from ``settings`` so test-time monkeypatches
apply.
"""

from __future__ import annotations

import json
import re
from typing import Awaitable, Callable

from app.core.config import settings

# (path pattern, limit getter, machine-readable error code). Getters read
# settings lazily — the limit is a property of request time, not boot time.
_RULES: tuple[tuple[re.Pattern[str], Callable[[], int], str], ...] = (
    (
        re.compile(r"^/api/v1/g/\d+/imports/envelope$"),
        lambda: settings.IMPORT_MAX_ENVELOPE_BYTES,
        "IMPORT_TOO_LARGE",
    ),
    (
        # Multipart adds framing overhead around the zip; allow 1 MiB slack
        # over the cap the handler's bounded read enforces exactly.
        re.compile(r"^/api/v1/g/\d+/imports/backup$"),
        lambda: settings.IMPORT_MAX_BACKUP_UPLOAD_BYTES + 1_048_576,
        "IMPORT_TOO_LARGE",
    ),
)


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rule = self._match(scope.get("path", ""))
        if rule is None:
            await self.app(scope, receive, send)
            return
        limit, code = rule

        # Fast path: an honest Content-Length is rejected before ANY body
        # bytes are read.
        declared = _content_length(scope)
        if declared is not None and declared > limit:
            await _send_413(send, code)
            return

        # Streaming backstop: count what actually arrives (chunked requests
        # declare nothing; a lying Content-Length under-declares).
        received = 0
        over_limit = False
        response_started = False
        replaced = False

        async def limited_receive():
            nonlocal received, over_limit
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    over_limit = True
                    raise _BodyTooLarge()
            return message

        async def tracking_send(message):
            nonlocal response_started, replaced
            if over_limit and not response_started:
                # The framework converted the aborted body read into its own
                # error response (FastAPI reports a 400 body-parse failure);
                # the true cause is the size cap — answer 413 instead.
                if message["type"] == "http.response.start":
                    replaced = True
                    response_started = True
                    await _send_413(send, code)
                    return
            if replaced and message["type"] == "http.response.body":
                return  # swallow the framework error body; ours already went
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            # The app propagated the aborted read without responding — answer
            # directly (if headers already went out the connection is
            # unsalvageable and closing it is the only honest signal).
            if not response_started:
                await _send_413(send, code)

    @staticmethod
    def _match(path: str) -> tuple[int, str] | None:
        for pattern, limit_getter, code in _RULES:
            if pattern.match(path):
                return limit_getter(), code
        return None


def _content_length(scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


async def _send_413(send: Callable[..., Awaitable[None]], code: str) -> None:
    body = json.dumps({"detail": code}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
