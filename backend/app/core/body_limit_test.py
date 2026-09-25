"""Which request bodies the transport bounds, and how tightly."""

from __future__ import annotations

import json

import pytest

from app.core.body_limit import (
    DEFAULT_MAX_REQUEST_BYTES,
    DOCUMENT_MAX_REQUEST_BYTES,
    MULTIPART_MAX_REQUEST_BYTES,
    _RULES,
    BodySizeLimitMiddleware,
    _bound_for,
)
from app.core.messages import CommonMessages
from app.services.import_engine import limits as import_limits
from app.services.marketplace import listing_assets, tool_listings
from app.services.tenant import attachments, galleries

pytestmark = pytest.mark.unit


def _limit(path: str) -> int | None:
    for pattern, limit, _code in _RULES:
        if pattern.match(path):
            return limit()
    return None


def test_the_atlassian_routes_are_bounded_where_they_are():
    """The connect and the import take a handful of strings; the export
    upload takes a zip as large as a backup."""
    connect = _limit("/api/v1/c/1/imports/atlassian/connect")
    start = _limit("/api/v1/c/1/imports/atlassian/import")
    export = _limit("/api/v1/c/1/imports/atlassian/export")
    assert connect is not None and connect == start
    assert export is not None and export > import_limits.IMPORT_MAX_BACKUP_UPLOAD_BYTES
    assert export == _limit("/api/v1/c/1/imports/backup")


def _bound(path: str, content_type: bytes = b"application/json") -> tuple[int, str]:
    return _bound_for({"path": path, "headers": [(b"content-type", content_type)]})


def test_a_route_no_rule_names_still_has_a_bound():
    assert _bound("/api/v1/c/1/tasks/") == (
        DEFAULT_MAX_REQUEST_BYTES,
        CommonMessages.REQUEST_TOO_LARGE,
    )
    assert _bound("/api/v1/auth/token") == (
        DEFAULT_MAX_REQUEST_BYTES,
        CommonMessages.REQUEST_TOO_LARGE,
    )


def test_a_multipart_upload_gets_room_for_the_largest_file_a_route_takes():
    limit, _ = _bound(
        "/api/v1/c/1/documents/upload",
        b"multipart/form-data; boundary=x",
    )
    assert limit == MULTIPART_MAX_REQUEST_BYTES
    assert limit > attachments.MAX_DOCUMENT_FILE_SIZE
    assert limit > galleries.MAX_IMAGE_BYTES
    # A listing sends all of its pictures in one request, beside its body.
    listing = (
        listing_assets.MAX_LISTING_IMAGES * listing_assets.MAX_IMAGE_BYTES
        + tool_listings.MAX_LISTING_BODY_BYTES
    )
    assert limit > listing


def test_the_default_leaves_room_for_a_calendar_import():
    """The largest JSON body no rule names is an iCalendar import."""
    assert DEFAULT_MAX_REQUEST_BYTES > 2 * 2_000_000


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/c/1/documents/",
        "/api/v1/c/1/documents",
        "/api/v1/c/1/documents/42",
        "/api/v1/c/1/wikis/3/pages",
        "/api/v1/c/1/wikis/3/pages/9",
        "/api/v1/c/1/collaboration/documents/42/collaborate",
        "/api/v1/c/1/collaboration/wikis/3/pages/9/collaborate",
    ],
)
def test_the_routes_that_write_a_document_take_a_whiteboard(path):
    assert _limit(path) == DOCUMENT_MAX_REQUEST_BYTES


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/c/1/documents/42/comments",
        "/api/v1/c/1/documents/42/duplicate",
        "/api/v1/c/1/wikis/3",
    ],
)
def test_the_document_rule_names_only_the_routes_that_carry_content(path):
    assert _limit(path) is None


async def _run(
    headers: list[tuple[bytes, bytes]], chunks: list[bytes]
) -> tuple[int, bytes]:
    """Drive the middleware around an app that reads its whole body."""

    async def app(scope, receive, send):
        while (await receive()).get("more_body"):
            pass
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    pending = [
        {"type": "http.request", "body": c, "more_body": i < len(chunks) - 1}
        for i, c in enumerate(chunks)
    ]

    async def receive():
        return pending.pop(0)

    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "path": "/api/v1/c/1/tasks/", "headers": headers}
    await BodySizeLimitMiddleware(app)(scope, receive, send)
    return sent[0]["status"], b"".join(m.get("body", b"") for m in sent[1:])


async def test_a_declared_length_over_the_default_is_refused_unread():
    status, body = await _run(
        [(b"content-length", str(DEFAULT_MAX_REQUEST_BYTES + 1).encode())],
        [b""],
    )
    assert status == 413
    assert json.loads(body)["detail"] == CommonMessages.REQUEST_TOO_LARGE


async def test_a_chunked_body_over_the_default_is_cut_off():
    chunk = b"x" * (1024 * 1024)
    status, body = await _run([], [chunk] * 5)
    assert status == 413
    assert json.loads(body)["detail"] == CommonMessages.REQUEST_TOO_LARGE


async def test_a_body_under_the_default_goes_through():
    status, body = await _run([], [b"{}"])
    assert (status, body) == (200, b"ok")
