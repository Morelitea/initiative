"""Advanced tool CRUD endpoint tests.

Covers the two scopes (initiative vs guild-wide/admin-only), the jsonb `data`
round-trip, the feature gate, and that guild-wide tools reject sharing.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.models.tenant.initiative import Initiative
from app.testing import route_session_to_guild

pytestmark = pytest.mark.integration


async def _enable_advanced_tool(session: AsyncSession, initiative) -> None:
    await route_session_to_guild(session, initiative.guild_id)
    init = await session.get(Initiative, initiative.id)
    init.advanced_tool_enabled = True
    session.add(init)
    await session.commit()


async def test_create_initiative_scoped_roundtrips_data(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_advanced_tool(session, a.initiative)

    blob = {"steps": [{"type": "http", "url": "https://x?a=1&b=2"}], "on": "webhook"}
    response = await client.post(
        a.g("/advanced-tools/"),
        headers=a.headers,
        json={"name": "Nightly sync", "data": blob, "initiative_id": a.initiative.id},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["name"] == "Nightly sync"
    assert data["initiative_id"] == a.initiative.id
    # The jsonb blob is stored verbatim — not HTML-sanitized (the & in the URL survives).
    assert data["data"] == blob


async def test_create_scoped_feature_disabled_forbidden(
    client: AsyncClient, acting_user
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    response = await client.post(
        a.g("/advanced-tools/"),
        headers=a.headers,
        json={"name": "x", "initiative_id": a.initiative.id},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "ADVANCED_TOOL_NOT_ENABLED"


async def test_create_guild_wide_admin_only(client: AsyncClient, acting_user):
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    response = await client.post(
        admin.g("/advanced-tools/"),
        headers=admin.headers,
        json={"name": "Guild automation", "data": {"k": "v"}},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["initiative_id"] is None
    tool_id = body["id"]

    # A plain member can't create a guild-wide tool...
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    forbidden = await client.post(
        member.g("/advanced-tools/"),
        headers=member.headers,
        json={"name": "nope"},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "ADVANCED_TOOL_GUILD_WIDE_REQUIRES_ADMIN"

    # ...and can't even see the admin's guild-wide tool (RLS admin-only).
    hidden = await client.get(
        member.g(f"/advanced-tools/{tool_id}"), headers=member.headers
    )
    assert hidden.status_code == 404


async def test_guild_wide_rejects_sharing(client: AsyncClient, acting_user):
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    created = await client.post(
        admin.g("/advanced-tools/"), headers=admin.headers, json={"name": "gw"}
    )
    tool_id = created.json()["id"]

    response = await client.put(
        admin.g(f"/advanced-tools/{tool_id}/grants"),
        headers=admin.headers,
        json=[{"all_initiative_members": True, "level": "read"}],
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "ADVANCED_TOOL_GUILD_WIDE_NOT_SHAREABLE"


async def test_update_data_and_delete(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_advanced_tool(session, a.initiative)
    created = await client.post(
        a.g("/advanced-tools/"),
        headers=a.headers,
        json={"name": "wf", "data": {"v": 1}, "initiative_id": a.initiative.id},
    )
    tool_id = created.json()["id"]

    patched = await client.patch(
        a.g(f"/advanced-tools/{tool_id}"),
        headers=a.headers,
        json={"data": {"v": 2, "added": True}},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"] == {"v": 2, "added": True}

    deleted = await client.delete(a.g(f"/advanced-tools/{tool_id}"), headers=a.headers)
    assert deleted.status_code == 204
    gone = await client.get(a.g(f"/advanced-tools/{tool_id}"), headers=a.headers)
    assert gone.status_code == 404


async def test_list_includes_scoped_and_guild_wide_for_admin(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_advanced_tool(session, a.initiative)
    await client.post(
        a.g("/advanced-tools/"),
        headers=a.headers,
        json={"name": "scoped", "initiative_id": a.initiative.id},
    )
    await client.post(
        a.g("/advanced-tools/"), headers=a.headers, json={"name": "guildwide"}
    )
    response = await client.get(a.g("/advanced-tools/"), headers=a.headers)
    assert response.status_code == 200
    names = {t["name"] for t in response.json()["items"]}
    assert {"scoped", "guildwide"} <= names
