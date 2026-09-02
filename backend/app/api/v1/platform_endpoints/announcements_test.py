"""Integration tests for /api/v1/announcements."""

from __future__ import annotations

import struct
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.announcement import Announcement
from app.models.platform.user import UserRole
from app.testing.factories import create_user, get_auth_headers


@pytest.fixture(autouse=True)
def _no_shipped_builtins(monkeypatch):
    """See the service suite: what this build ships is not this suite's subject."""
    from app.core import builtin_announcements as builtins_module
    from app.services.platform import announcements as service

    monkeypatch.setattr(builtins_module, "BUILTIN_ANNOUNCEMENTS", ())
    monkeypatch.setattr(service, "BUILTIN_ANNOUNCEMENTS", ())


def _png(width: int = 8, height: int = 8, padding: int = 0) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
        + b"\x00" * padding
    )


def _body(**overrides) -> dict:
    payload = {
        "title": "Board view is new",
        "category": "feature",
        "sections": [{"heading": "Look", "body": "At this"}],
        "published_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
    }
    payload.update(overrides)
    return payload


async def _author(session: AsyncSession):
    user = await create_user(session, role=UserRole.operator)
    return user, get_auth_headers(user)


@pytest.mark.integration
async def test_a_reader_sees_a_published_announcement(
    client: AsyncClient, session: AsyncSession
):
    _, author_headers = await _author(session)
    reader = await create_user(session)

    created = await client.post(
        "/api/v1/announcements/admin", headers=author_headers, json=_body()
    )
    assert created.status_code == 201

    listed = await client.get("/api/v1/announcements", headers=get_auth_headers(reader))
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert [item["title"] for item in items] == ["Board view is new"]
    assert items[0]["sections"][0]["heading"] == "Look"


@pytest.mark.integration
async def test_a_draft_is_invisible_to_a_reader(
    client: AsyncClient, session: AsyncSession
):
    _, author_headers = await _author(session)
    reader = await create_user(session)

    await client.post(
        "/api/v1/announcements/admin",
        headers=author_headers,
        json=_body(published_at=None),
    )

    listed = await client.get("/api/v1/announcements", headers=get_auth_headers(reader))
    assert listed.json()["items"] == []


@pytest.mark.integration
async def test_dismissing_removes_it_from_the_next_fetch(
    client: AsyncClient, session: AsyncSession
):
    _, author_headers = await _author(session)
    reader = await create_user(session)
    reader_headers = get_auth_headers(reader)

    created = await client.post(
        "/api/v1/announcements/admin", headers=author_headers, json=_body()
    )
    key = created.json()["key"]

    seen = await client.post(
        f"/api/v1/announcements/{key}/seen", headers=reader_headers
    )
    assert seen.status_code == 204
    still_there = await client.get("/api/v1/announcements", headers=reader_headers)
    assert len(still_there.json()["items"]) == 1

    dismissed = await client.post(
        f"/api/v1/announcements/{key}/dismiss", headers=reader_headers
    )
    assert dismissed.status_code == 204

    after = await client.get("/api/v1/announcements", headers=reader_headers)
    assert after.json()["items"] == []


@pytest.mark.integration
async def test_the_archive_returns_what_the_queue_has_finished_with(
    client: AsyncClient, session: AsyncSession
):
    _, author_headers = await _author(session)
    reader = await create_user(session)
    reader_headers = get_auth_headers(reader)

    created = await client.post(
        "/api/v1/announcements/admin", headers=author_headers, json=_body()
    )
    key = created.json()["key"]
    await client.post(f"/api/v1/announcements/{key}/dismiss", headers=reader_headers)

    assert (await client.get("/api/v1/announcements", headers=reader_headers)).json()[
        "items"
    ] == []

    archive = await client.get(
        "/api/v1/announcements",
        headers=reader_headers,
        params={"include_dismissed": True},
    )
    assert [item["title"] for item in archive.json()["items"]] == ["Board view is new"]
    assert archive.json()["items"][0]["dismissed_at"] is not None


@pytest.mark.integration
async def test_a_notice_that_asks_for_two_dismissals_survives_the_first(
    client: AsyncClient, session: AsyncSession
):
    _, author_headers = await _author(session)
    reader = await create_user(session)
    reader_headers = get_auth_headers(reader)

    created = await client.post(
        "/api/v1/announcements/admin",
        headers=author_headers,
        json=_body(dismissals_required=2),
    )
    key = created.json()["key"]

    await client.post(f"/api/v1/announcements/{key}/dismiss", headers=reader_headers)
    after_one = await client.get("/api/v1/announcements", headers=reader_headers)
    assert len(after_one.json()["items"]) == 1
    assert after_one.json()["items"][0]["dismiss_count"] == 1

    await client.post(f"/api/v1/announcements/{key}/dismiss", headers=reader_headers)
    after_two = await client.get("/api/v1/announcements", headers=reader_headers)
    assert after_two.json()["items"] == []


@pytest.mark.integration
async def test_pages_and_a_trigger_route_survive_the_round_trip(
    client: AsyncClient, session: AsyncSession
):
    _, author_headers = await _author(session)
    reader = await create_user(session)

    created = await client.post(
        "/api/v1/announcements/admin",
        headers=author_headers,
        json=_body(
            trigger_route="/c/*/i/*/projects/**",
            sections=[
                {"heading": "First", "body": "one"},
                {"heading": "Second", "body": "two", "starts_page": True},
            ],
        ),
    )
    assert created.status_code == 201

    listed = await client.get("/api/v1/announcements", headers=get_auth_headers(reader))
    item = listed.json()["items"][0]
    assert item["trigger_route"] == "/c/*/i/*/projects/**"
    assert [section["starts_page"] for section in item["sections"]] == [False, True]


@pytest.mark.integration
async def test_a_trigger_route_that_is_not_a_path_is_refused(
    client: AsyncClient, session: AsyncSession
):
    _, author_headers = await _author(session)
    response = await client.post(
        "/api/v1/announcements/admin",
        headers=author_headers,
        json=_body(trigger_route="https://elsewhere.example/x"),
    )
    assert response.status_code == 422


@pytest.mark.integration
async def test_a_receipt_for_something_that_does_not_exist_is_a_404(
    client: AsyncClient, session: AsyncSession
):
    reader = await create_user(session)
    response = await client.post(
        "/api/v1/announcements/db:424242/dismiss", headers=get_auth_headers(reader)
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "ANNOUNCEMENT_NOT_FOUND"


@pytest.mark.integration
async def test_a_malformed_key_is_rejected_before_any_lookup(
    client: AsyncClient, session: AsyncSession
):
    reader = await create_user(session)
    response = await client.post(
        "/api/v1/announcements/whatever/dismiss", headers=get_auth_headers(reader)
    )
    assert response.status_code == 422


@pytest.mark.integration
async def test_writing_an_announcement_needs_the_capability(
    client: AsyncClient, session: AsyncSession
):
    member = await create_user(session, role=UserRole.member)
    moderator = await create_user(session, role=UserRole.moderator)

    for user in (member, moderator):
        response = await client.post(
            "/api/v1/announcements/admin", headers=get_auth_headers(user), json=_body()
        )
        assert response.status_code == 403

    listed = await client.get(
        "/api/v1/announcements/admin", headers=get_auth_headers(member)
    )
    assert listed.status_code == 403


@pytest.mark.integration
async def test_an_author_sees_drafts_in_the_admin_list(
    client: AsyncClient, session: AsyncSession
):
    _, author_headers = await _author(session)
    await client.post(
        "/api/v1/announcements/admin",
        headers=author_headers,
        json=_body(title="A draft", published_at=None),
    )

    listed = await client.get("/api/v1/announcements/admin", headers=author_headers)
    assert listed.status_code == 200
    titles = [item["title"] for item in listed.json()["items"]]
    assert "A draft" in titles


@pytest.mark.integration
async def test_editing_publishes_and_unpublishes(
    client: AsyncClient, session: AsyncSession
):
    _, author_headers = await _author(session)
    reader = await create_user(session)
    reader_headers = get_auth_headers(reader)

    created = await client.post(
        "/api/v1/announcements/admin",
        headers=author_headers,
        json=_body(published_at=None),
    )
    announcement_id = created.json()["id"]

    published = await client.patch(
        f"/api/v1/announcements/admin/{announcement_id}",
        headers=author_headers,
        json={
            "published_at": (
                datetime.now(timezone.utc) - timedelta(minutes=1)
            ).isoformat()
        },
    )
    assert published.status_code == 200
    assert (
        len(
            (await client.get("/api/v1/announcements", headers=reader_headers)).json()[
                "items"
            ]
        )
        == 1
    )

    await client.patch(
        f"/api/v1/announcements/admin/{announcement_id}",
        headers=author_headers,
        json={"clear_published_at": True},
    )
    assert (await client.get("/api/v1/announcements", headers=reader_headers)).json()[
        "items"
    ] == []


@pytest.mark.integration
async def test_deleting_an_announcement_removes_it(
    client: AsyncClient, session: AsyncSession
):
    _, author_headers = await _author(session)
    created = await client.post(
        "/api/v1/announcements/admin", headers=author_headers, json=_body()
    )
    announcement_id = created.json()["id"]

    deleted = await client.delete(
        f"/api/v1/announcements/admin/{announcement_id}", headers=author_headers
    )
    assert deleted.status_code == 204
    assert await session.get(Announcement, announcement_id) is None

    missing = await client.delete(
        f"/api/v1/announcements/admin/{announcement_id}", headers=author_headers
    )
    assert missing.status_code == 404


@pytest.mark.integration
async def test_an_announcement_needs_a_section_with_something_in_it(
    client: AsyncClient, session: AsyncSession
):
    _, author_headers = await _author(session)
    response = await client.post(
        "/api/v1/announcements/admin",
        headers=author_headers,
        json=_body(sections=[{"heading": "   "}]),
    )
    assert response.status_code == 422


@pytest.mark.integration
async def test_a_section_picture_must_be_a_path_or_an_http_url(
    client: AsyncClient, session: AsyncSession
):
    _, author_headers = await _author(session)
    response = await client.post(
        "/api/v1/announcements/admin",
        headers=author_headers,
        json=_body(
            sections=[{"body": "x", "image_url": "javascript:alert(1)"}],
        ),
    )
    assert response.status_code == 422


@pytest.mark.integration
async def test_uploading_a_picture_returns_a_url_that_serves_it(
    client: AsyncClient, session: AsyncSession
):
    _, author_headers = await _author(session)
    reader = await create_user(session)

    uploaded = await client.post(
        "/api/v1/announcements/admin/images",
        headers=author_headers,
        files={"file": ("shot.png", _png(padding=64), "image/png")},
    )
    assert uploaded.status_code == 201
    payload = uploaded.json()
    assert payload["url"].endswith(payload["sha256"])
    assert payload["content_type"] == "image/png"

    served = await client.get(payload["url"], headers=get_auth_headers(reader))
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"


@pytest.mark.integration
async def test_uploading_something_that_is_not_an_image_is_refused(
    client: AsyncClient, session: AsyncSession
):
    _, author_headers = await _author(session)
    response = await client.post(
        "/api/v1/announcements/admin/images",
        headers=author_headers,
        files={"file": ("notes.txt", b"just some text, honestly", "image/png")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "ANNOUNCEMENT_IMAGE_UNSUPPORTED_TYPE"


@pytest.mark.integration
async def test_uploading_a_picture_needs_the_capability(
    client: AsyncClient, session: AsyncSession
):
    member = await create_user(session)
    response = await client.post(
        "/api/v1/announcements/admin/images",
        headers=get_auth_headers(member),
        files={"file": ("shot.png", _png(), "image/png")},
    )
    assert response.status_code == 403
