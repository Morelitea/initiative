"""Endpoint tests for the mention search (``/comments/mentions/search``)."""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.testing.factories import create_initiative_member, create_user


@pytest.mark.integration
async def test_mention_search_users_paginated_with_avatars(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """User mention search returns the paginated envelope; each user item
    carries an avatar so the picker can render a face."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    for name in ("Alice Ant", "Bob Bee", "Cara Cat"):
        member = await create_user(session, full_name=name, avatar_base64="data:x")
        await create_initiative_member(session, admin.initiative, member)

    response = await client.get(
        admin.g("/comments/mentions/search"),
        headers=admin.headers,
        params={
            "entity_type": "user",
            "initiative_id": admin.initiative.id,
            "page_size": 2,
        },
    )

    assert response.status_code == 200
    body = response.json()
    # Envelope shape mirrors the member search endpoints.
    assert set(body.keys()) == {
        "items",
        "total_count",
        "page",
        "page_size",
        "has_next",
        "has_prev",
    }
    assert body["page_size"] == 2
    assert len(body["items"]) == 2
    assert body["total_count"] >= 3  # 3 added members (+ maybe the admin)
    assert body["has_next"] is True
    item = body["items"][0]
    assert item["type"] == "user"
    assert "avatar_base64" in item and "avatar_url" in item


@pytest.mark.integration
async def test_mention_search_users_filters_by_name(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The `q` param filters user suggestions by name (case-insensitive)."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    for name in ("Alice Ant", "Bob Bee"):
        member = await create_user(session, full_name=name)
        await create_initiative_member(session, admin.initiative, member)

    response = await client.get(
        admin.g("/comments/mentions/search"),
        headers=admin.headers,
        params={
            "entity_type": "user",
            "initiative_id": admin.initiative.id,
            "q": "alice",
        },
    )

    assert response.status_code == 200
    body = response.json()
    names = {item["display_text"] for item in body["items"]}
    assert "Alice Ant" in names
    assert "Bob Bee" not in names


@pytest.mark.integration
async def test_mention_search_unknown_initiative_404(
    client: AsyncClient, session: AsyncSession, acting_user
):
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    response = await client.get(
        admin.g("/comments/mentions/search"),
        headers=admin.headers,
        params={"entity_type": "user", "initiative_id": 999999},
    )
    assert response.status_code == 404
