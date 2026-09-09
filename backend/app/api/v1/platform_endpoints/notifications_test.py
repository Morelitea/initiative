"""Integration tests for /api/v1/notifications.

These run through the real-role ``client`` (bare ``app_user`` login +
``SET ROLE platform_<tier>``), guarding the 0.54.0 regression where the
endpoints ran as the de-granted bare login role and every request failed
with ``permission denied for table notifications``.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.notification import NotificationType
from app.services.platform import user_notifications
from app.testing.factories import (
    create_guild,
    create_user,
    get_auth_headers,
    set_notification_prefs,
)


async def _seed_notification(session: AsyncSession, user_id: int) -> int:
    notification = await user_notifications.create_notification(
        session,
        user_id=user_id,
        notification_type=NotificationType.task_assignment,
        data={"task_title": "Ship it"},
    )
    await session.commit()
    assert notification.id is not None
    return notification.id


@pytest.mark.integration
async def test_list_notifications(client: AsyncClient, session: AsyncSession):
    user = await create_user(session)
    await _seed_notification(session, user.id)

    response = await client.get(
        "/api/v1/notifications/", headers=get_auth_headers(user)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["unread_count"] == 1
    assert len(body["notifications"]) == 1
    assert body["notifications"][0]["type"] == "task_assignment"


@pytest.mark.integration
async def test_unread_places(client: AsyncClient, session: AsyncSession):
    """Where the dots go. A notification with no community is still a place —
    that is what makes "anything unread at all" the same question."""
    user = await create_user(session)
    await _seed_notification(session, user.id)

    response = await client.get(
        "/api/v1/notifications/unread", headers=get_auth_headers(user)
    )
    assert response.status_code == 200
    assert response.json() == {
        "places": [{"guild_id": None, "initiative_id": None, "tool": None}]
    }


@pytest.mark.integration
async def test_unread_places_carries_the_whole_tree(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.comment_on_task,
        data={"guild_id": guild.id, "initiative_id": 9, "entity_type": "project"},
    )
    await session.commit()

    response = await client.get(
        "/api/v1/notifications/unread", headers=get_auth_headers(user)
    )
    assert response.json()["places"] == [
        {"guild_id": guild.id, "initiative_id": 9, "tool": "project"}
    ]


@pytest.mark.integration
async def test_reading_everything_empties_the_places(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    await _seed_notification(session, user.id)
    headers = get_auth_headers(user)

    await client.post("/api/v1/notifications/read-all", headers=headers)

    response = await client.get("/api/v1/notifications/unread", headers=headers)
    assert response.json() == {"places": []}


@pytest.mark.integration
async def test_the_popover_can_take_every_unread_page(
    client: AsyncClient, session: AsyncSession
):
    """No cap: the popover follows the cursor to the end, which is what makes
    a number on the bell unnecessary."""
    user = await create_user(session)
    for _ in range(5):
        await _seed_notification(session, user.id)
    headers = get_auth_headers(user)

    seen: list[int] = []
    cursor: str | None = None
    for _ in range(10):  # bounded so a broken cursor cannot spin forever
        params = {"limit": 2, "unread_only": "true"}
        if cursor:
            params["cursor"] = cursor
        body = (
            await client.get("/api/v1/notifications/", headers=headers, params=params)
        ).json()
        seen.extend(n["id"] for n in body["notifications"])
        cursor = body["next_cursor"]
        if not cursor:
            break

    assert cursor is None
    assert len(seen) == 5
    assert len(set(seen)) == 5


@pytest.mark.integration
async def test_marking_unread_puts_a_line_back(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    notification_id = await _seed_notification(session, user.id)
    headers = get_auth_headers(user)

    await client.post(f"/api/v1/notifications/{notification_id}/read", headers=headers)
    response = await client.post(
        f"/api/v1/notifications/{notification_id}/unread", headers=headers
    )

    assert response.status_code == 200
    assert response.json()["read_at"] is None


@pytest.mark.integration
async def test_dismissing_removes_the_line(client: AsyncClient, session: AsyncSession):
    user = await create_user(session)
    notification_id = await _seed_notification(session, user.id)
    headers = get_auth_headers(user)

    response = await client.delete(
        f"/api/v1/notifications/{notification_id}", headers=headers
    )
    assert response.status_code == 204

    body = (await client.get("/api/v1/notifications/", headers=headers)).json()
    assert body["notifications"] == []
    assert body["unread_count"] == 0


@pytest.mark.integration
async def test_read_all_can_clear_one_community(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    cleared = await create_guild(session, creator=user, name="Cleared")
    kept = await create_guild(session, creator=user, name="Kept")
    for guild in (cleared, kept):
        await user_notifications.create_notification(
            session,
            user_id=user.id,
            notification_type=NotificationType.comment_on_task,
            data={"guild_id": guild.id},
        )
    await session.commit()
    headers = get_auth_headers(user)

    await client.post(
        "/api/v1/notifications/read-all",
        headers=headers,
        params={"guild_id": cleared.id},
    )

    places = (await client.get("/api/v1/notifications/unread", headers=headers)).json()[
        "places"
    ]
    assert places == [{"guild_id": kept.id, "initiative_id": None, "tool": None}]


@pytest.mark.integration
async def test_the_bell_can_be_switched_off_for_a_category(
    client: AsyncClient, session: AsyncSession
):
    """The whole point of in_app being a channel."""
    user = await create_user(session)
    await set_notification_prefs(
        session, user, {"categories": {"assignments": {"in_app": False}}}
    )
    written = await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.task_assignment,
        data={"task_title": "Ship it"},
    )
    await session.commit()

    assert written is None
    body = (
        await client.get("/api/v1/notifications/", headers=get_auth_headers(user))
    ).json()
    assert body["notifications"] == []


@pytest.mark.integration
async def test_mark_notification_read(client: AsyncClient, session: AsyncSession):
    user = await create_user(session)
    notification_id = await _seed_notification(session, user.id)
    headers = get_auth_headers(user)

    response = await client.post(
        f"/api/v1/notifications/{notification_id}/read", headers=headers
    )
    assert response.status_code == 200
    assert response.json()["read_at"] is not None

    listed = await client.get("/api/v1/notifications/", headers=headers)
    assert listed.json()["unread_count"] == 0


@pytest.mark.integration
async def test_mark_all_notifications_read(client: AsyncClient, session: AsyncSession):
    user = await create_user(session)
    await _seed_notification(session, user.id)
    await _seed_notification(session, user.id)

    response = await client.post(
        "/api/v1/notifications/read-all", headers=get_auth_headers(user)
    )
    assert response.status_code == 200
    assert response.json() == {"unread_count": 0}


@pytest.mark.integration
async def test_cannot_read_other_users_notification(
    client: AsyncClient, session: AsyncSession
):
    owner = await create_user(session)
    other = await create_user(session)
    notification_id = await _seed_notification(session, owner.id)

    response = await client.post(
        f"/api/v1/notifications/{notification_id}/read",
        headers=get_auth_headers(other),
    )
    assert response.status_code == 404
