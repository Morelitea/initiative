"""
Integration tests for queue endpoints — CRUD, items, turns, permissions.
"""

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import GuildRole
from app.models.initiative import InitiativeRoleModel
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_user,
    get_guild_headers,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _setup_guild_and_initiative(session: AsyncSession):
    """Create admin user, guild, membership, and initiative."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, admin, name="Test Initiative")
    return admin, guild, initiative


async def _setup_with_member(session: AsyncSession):
    """Create admin + regular member with guild/initiative membership."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    member = await create_user(session, email="member@example.com")
    await create_guild_membership(session, user=member, guild=guild)
    await create_initiative_member(session, initiative, member, role_name="member")
    return admin, member, guild, initiative


async def _create_queue_via_api(client: AsyncClient, headers: dict, initiative_id: int, name: str = "Test Queue") -> dict:
    """Create a queue via API and return the response data."""
    response = await client.post(
        "/api/v1/queues/",
        headers=headers,
        json={"name": name, "initiative_id": initiative_id},
    )
    assert response.status_code == 201
    return response.json()


async def _add_item_via_api(client: AsyncClient, headers: dict, queue_id: int, label: str, position: int = 0) -> dict:
    """Add an item to a queue via API."""
    response = await client.post(
        f"/api/v1/queues/{queue_id}/items",
        headers=headers,
        json={"label": label, "position": position},
    )
    assert response.status_code == 201
    return response.json()


# ---------------------------------------------------------------------------
# Queue CRUD
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_queue(client: AsyncClient, session: AsyncSession):
    """PM can create a queue."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)

    response = await client.post(
        "/api/v1/queues/",
        headers=headers,
        json={
            "name": "Initiative Order",
            "description": "Turn tracker",
            "initiative_id": initiative.id,
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Initiative Order"
    assert data["description"] == "Turn tracker"
    assert data["initiative_id"] == initiative.id
    assert data["created_by_id"] == admin.id
    assert data["is_active"] is False
    assert data["current_round"] == 1


@pytest.mark.integration
async def test_create_queue_non_pm_forbidden(client: AsyncClient, session: AsyncSession):
    """Non-PM member cannot create a queue (unless role allows it)."""
    admin, member, guild, initiative = await _setup_with_member(session)
    headers = get_guild_headers(guild, member)

    response = await client.post(
        "/api/v1/queues/",
        headers=headers,
        json={
            "name": "Forbidden Queue",
            "initiative_id": initiative.id,
        },
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_list_queues(client: AsyncClient, session: AsyncSession):
    """Admin can list queues."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    await _create_queue_via_api(client, headers, initiative.id, "Listed Queue")

    response = await client.get("/api/v1/queues/", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] >= 1
    names = [q["name"] for q in data["items"]]
    assert "Listed Queue" in names


@pytest.mark.integration
async def test_get_queue(client: AsyncClient, session: AsyncSession):
    """Owner can fetch queue details."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data = await _create_queue_via_api(client, headers, initiative.id)

    response = await client.get(f"/api/v1/queues/{queue_data['id']}", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == queue_data["id"]
    assert data["my_permission_level"] == "owner"


@pytest.mark.integration
async def test_update_queue(client: AsyncClient, session: AsyncSession):
    """Owner can update queue name/description."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data = await _create_queue_via_api(client, headers, initiative.id)

    response = await client.patch(
        f"/api/v1/queues/{queue_data['id']}",
        headers=headers,
        json={"name": "Updated Name", "description": "Updated desc"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Name"
    assert data["description"] == "Updated desc"


@pytest.mark.integration
async def test_delete_queue(client: AsyncClient, session: AsyncSession):
    """Owner can delete a queue."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data = await _create_queue_via_api(client, headers, initiative.id)

    response = await client.delete(f"/api/v1/queues/{queue_data['id']}", headers=headers)
    assert response.status_code == 204

    # Verify gone
    response = await client.get(f"/api/v1/queues/{queue_data['id']}", headers=headers)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Queue Items
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_add_queue_item(client: AsyncClient, session: AsyncSession):
    """Owner can add an item to a queue."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data = await _create_queue_via_api(client, headers, initiative.id)

    response = await client.post(
        f"/api/v1/queues/{queue_data['id']}/items",
        headers=headers,
        json={"label": "Player 1", "position": 15, "color": "#FF0000"},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["label"] == "Player 1"
    assert data["position"] == 15
    assert data["color"] == "#FF0000"


@pytest.mark.integration
async def test_update_queue_item(client: AsyncClient, session: AsyncSession):
    """Owner can update an item."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data = await _create_queue_via_api(client, headers, initiative.id)
    item_data = await _add_item_via_api(client, headers, queue_data["id"], "Original")

    response = await client.patch(
        f"/api/v1/queues/{queue_data['id']}/items/{item_data['id']}",
        headers=headers,
        json={"label": "Renamed", "position": 5},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["label"] == "Renamed"
    assert data["position"] == 5


@pytest.mark.integration
async def test_delete_queue_item(client: AsyncClient, session: AsyncSession):
    """Owner can delete an item."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data = await _create_queue_via_api(client, headers, initiative.id)
    item_data = await _add_item_via_api(client, headers, queue_data["id"], "To Delete")

    response = await client.delete(
        f"/api/v1/queues/{queue_data['id']}/items/{item_data['id']}",
        headers=headers,
    )
    assert response.status_code == 204


@pytest.mark.integration
async def test_reorder_queue_items(client: AsyncClient, session: AsyncSession):
    """Owner can bulk-reorder items."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data = await _create_queue_via_api(client, headers, initiative.id)
    item_a = await _add_item_via_api(client, headers, queue_data["id"], "A", position=1)
    item_b = await _add_item_via_api(client, headers, queue_data["id"], "B", position=2)

    response = await client.put(
        f"/api/v1/queues/{queue_data['id']}/items/reorder",
        headers=headers,
        json={"items": [
            {"id": item_a["id"], "position": 20},
            {"id": item_b["id"], "position": 10},
        ]},
    )

    assert response.status_code == 200
    data = response.json()
    items_by_id = {i["id"]: i for i in data["items"]}
    assert items_by_id[item_a["id"]]["position"] == 20
    assert items_by_id[item_b["id"]]["position"] == 10


# ---------------------------------------------------------------------------
# Turn management
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_start_and_stop_queue(client: AsyncClient, session: AsyncSession):
    """Start activates the queue, stop deactivates it."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data = await _create_queue_via_api(client, headers, initiative.id)
    await _add_item_via_api(client, headers, queue_data["id"], "P1", position=10)

    # Start
    response = await client.post(f"/api/v1/queues/{queue_data['id']}/start", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["is_active"] is True
    assert data["current_item"] is not None

    # Stop
    response = await client.post(f"/api/v1/queues/{queue_data['id']}/stop", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["is_active"] is False


@pytest.mark.integration
async def test_advance_turn(client: AsyncClient, session: AsyncSession):
    """Advancing cycles through visible items."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data = await _create_queue_via_api(client, headers, initiative.id)
    await _add_item_via_api(client, headers, queue_data["id"], "A", position=10)
    await _add_item_via_api(client, headers, queue_data["id"], "B", position=20)

    # Start
    await client.post(f"/api/v1/queues/{queue_data['id']}/start", headers=headers)

    # Advance
    response = await client.post(f"/api/v1/queues/{queue_data['id']}/next", headers=headers)
    assert response.status_code == 200


@pytest.mark.integration
async def test_reset_queue(client: AsyncClient, session: AsyncSession):
    """Reset resets round to 1 and sets current to first visible item."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data = await _create_queue_via_api(client, headers, initiative.id)
    await _add_item_via_api(client, headers, queue_data["id"], "P1", position=5)

    await client.post(f"/api/v1/queues/{queue_data['id']}/start", headers=headers)

    response = await client.post(f"/api/v1/queues/{queue_data['id']}/reset", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["current_round"] == 1
    assert data["current_item"] is not None


# ---------------------------------------------------------------------------
# Permissions (DAC)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_set_queue_permissions(client: AsyncClient, session: AsyncSession):
    """Owner can set user permissions on a queue."""
    admin, member, guild, initiative = await _setup_with_member(session)
    headers = get_guild_headers(guild, admin)
    queue_data = await _create_queue_via_api(client, headers, initiative.id)

    response = await client.put(
        f"/api/v1/queues/{queue_data['id']}/permissions",
        headers=headers,
        json=[{"user_id": member.id, "level": "write"}],
    )

    assert response.status_code == 200
    data = response.json()
    member_perms = [p for p in data if p["user_id"] == member.id]
    assert len(member_perms) == 1
    assert member_perms[0]["level"] == "write"


@pytest.mark.integration
async def test_set_queue_role_permissions(client: AsyncClient, session: AsyncSession):
    """Owner can set role permissions on a queue."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data = await _create_queue_via_api(client, headers, initiative.id)

    # Find the member role
    result = await session.exec(
        select(InitiativeRoleModel).where(
            InitiativeRoleModel.initiative_id == initiative.id,
            InitiativeRoleModel.name == "member",
        )
    )
    member_role = result.one()

    response = await client.put(
        f"/api/v1/queues/{queue_data['id']}/role-permissions",
        headers=headers,
        json=[{"initiative_role_id": member_role.id, "level": "read"}],
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["initiative_role_id"] == member_role.id
    assert data[0]["level"] == "read"


@pytest.mark.integration
async def test_member_with_read_can_view_queue(client: AsyncClient, session: AsyncSession):
    """Member with read permission can view but not modify."""
    admin, member, guild, initiative = await _setup_with_member(session)
    admin_headers = get_guild_headers(guild, admin)
    queue_data = await _create_queue_via_api(client, admin_headers, initiative.id)

    # Grant read to member
    await client.put(
        f"/api/v1/queues/{queue_data['id']}/permissions",
        headers=admin_headers,
        json=[{"user_id": member.id, "level": "read"}],
    )

    member_headers = get_guild_headers(guild, member)

    # Can read
    response = await client.get(f"/api/v1/queues/{queue_data['id']}", headers=member_headers)
    assert response.status_code == 200

    # Cannot update
    response = await client.patch(
        f"/api/v1/queues/{queue_data['id']}",
        headers=member_headers,
        json={"name": "Hacked"},
    )
    assert response.status_code == 403


@pytest.mark.integration
async def test_member_without_permission_cannot_view(
    client: AsyncClient, session: AsyncSession
):
    """Member with no permission cannot access the queue."""
    admin, member, guild, initiative = await _setup_with_member(session)
    admin_headers = get_guild_headers(guild, admin)
    queue_data = await _create_queue_via_api(client, admin_headers, initiative.id)

    member_headers = get_guild_headers(guild, member)
    response = await client.get(f"/api/v1/queues/{queue_data['id']}", headers=member_headers)
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Item associations (tags, documents, tasks)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_set_queue_item_tags(client: AsyncClient, session: AsyncSession):
    """Owner can set tags on a queue item."""
    from app.models.tag import Tag

    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data = await _create_queue_via_api(client, headers, initiative.id)
    item_data = await _add_item_via_api(client, headers, queue_data["id"], "Tagged")

    # Create a tag
    tag = Tag(name="Priority", guild_id=guild.id)
    session.add(tag)
    await session.commit()
    await session.refresh(tag)

    response = await client.put(
        f"/api/v1/queues/{queue_data['id']}/items/{item_data['id']}/tags",
        headers=headers,
        json=[tag.id],
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["tags"]) == 1
    assert data["tags"][0]["id"] == tag.id


@pytest.mark.integration
async def test_create_queue_with_permissions(client: AsyncClient, session: AsyncSession):
    """Create a queue with inline role and user permissions."""
    admin, member, guild, initiative = await _setup_with_member(session)
    headers = get_guild_headers(guild, admin)

    result = await session.exec(
        select(InitiativeRoleModel).where(
            InitiativeRoleModel.initiative_id == initiative.id,
            InitiativeRoleModel.name == "member",
        )
    )
    member_role = result.one()

    response = await client.post(
        "/api/v1/queues/",
        headers=headers,
        json={
            "name": "With Perms",
            "initiative_id": initiative.id,
            "role_permissions": [{"initiative_role_id": member_role.id, "level": "read"}],
            "user_permissions": [{"user_id": member.id, "level": "write"}],
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert len(data["role_permissions"]) == 1
    user_perms = [p for p in data["permissions"] if p["user_id"] == member.id]
    assert len(user_perms) == 1
    assert user_perms[0]["level"] == "write"
