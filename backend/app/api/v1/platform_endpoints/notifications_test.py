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
from app.testing.factories import create_user, get_auth_headers


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
async def test_unread_count(client: AsyncClient, session: AsyncSession):
    user = await create_user(session)
    await _seed_notification(session, user.id)

    response = await client.get(
        "/api/v1/notifications/unread-count", headers=get_auth_headers(user)
    )
    assert response.status_code == 200
    assert response.json() == {"unread_count": 1}


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

    count_resp = await client.get("/api/v1/notifications/unread-count", headers=headers)
    assert count_resp.json() == {"unread_count": 0}


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
