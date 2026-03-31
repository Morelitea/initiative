"""
Integration tests for automation endpoints — flow CRUD, run history, graph validation.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.messages import AutomationsMessages
from app.models.guild import GuildRole
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_user,
    get_guild_headers,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _enable_automations():
    """Temporarily enable automations infra flag for all tests in this module."""
    original = settings.ENABLE_AUTOMATIONS
    settings.ENABLE_AUTOMATIONS = True
    yield
    settings.ENABLE_AUTOMATIONS = original


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_FLOW_DATA = {
    "nodes": [
        {"id": "t1", "type": "trigger", "data": {"event": "task.status_changed"}},
        {"id": "a1", "type": "action", "data": {"action": "send_notification"}},
    ],
    "edges": [
        {"source": "t1", "target": "a1"},
    ],
}


async def _setup_guild_and_initiative(session: AsyncSession):
    """Create admin user, guild, membership, and initiative with automations enabled."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(
        session, guild, admin,
        name="Test Initiative",
        automations_enabled=True,
    )
    return admin, guild, initiative


async def _setup_with_member(session: AsyncSession):
    """Create admin + regular member with guild/initiative membership."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    member = await create_user(session, email="member@example.com")
    await create_guild_membership(session, user=member, guild=guild)
    await create_initiative_member(session, initiative, member, role_name="member")
    return admin, member, guild, initiative


async def _create_flow_via_api(
    client: AsyncClient,
    headers: dict,
    initiative_id: int,
    name: str = "Test Flow",
    flow_data: dict | None = None,
) -> dict:
    """Create a flow via API and return the response data."""
    response = await client.post(
        "/api/v1/automations",
        headers=headers,
        json={
            "name": name,
            "initiative_id": initiative_id,
            "flow_data": flow_data or VALID_FLOW_DATA,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Flow CRUD
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_flow(client: AsyncClient, session: AsyncSession):
    """Admin can create an automation flow."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)

    response = await client.post(
        "/api/v1/automations",
        headers=headers,
        json={
            "name": "My Automation",
            "description": "Does things",
            "initiative_id": initiative.id,
            "flow_data": VALID_FLOW_DATA,
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "My Automation"
    assert data["description"] == "Does things"
    assert data["initiative_id"] == initiative.id
    assert data["created_by_id"] == admin.id
    assert data["enabled"] is False
    assert data["flow_data"] == VALID_FLOW_DATA


@pytest.mark.integration
async def test_create_flow_non_pm_forbidden(client: AsyncClient, session: AsyncSession):
    """Non-PM member without create_automations permission cannot create a flow."""
    admin, member, guild, initiative = await _setup_with_member(session)
    headers = get_guild_headers(guild, member)

    response = await client.post(
        "/api/v1/automations",
        headers=headers,
        json={
            "name": "Forbidden Flow",
            "initiative_id": initiative.id,
            "flow_data": VALID_FLOW_DATA,
        },
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_create_flow_invalid_graph_no_trigger(client: AsyncClient, session: AsyncSession):
    """Creating a flow with no trigger node returns 400."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)

    bad_flow = {
        "nodes": [
            {"id": "a1", "type": "action", "data": {}},
        ],
        "edges": [],
    }
    response = await client.post(
        "/api/v1/automations",
        headers=headers,
        json={
            "name": "Bad Flow",
            "initiative_id": initiative.id,
            "flow_data": bad_flow,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == AutomationsMessages.INVALID_FLOW_GRAPH


@pytest.mark.integration
async def test_create_flow_invalid_graph_cycle(client: AsyncClient, session: AsyncSession):
    """Creating a flow with a cycle returns 400."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)

    cyclic_flow = {
        "nodes": [
            {"id": "t1", "type": "trigger", "data": {}},
            {"id": "a1", "type": "action", "data": {}},
            {"id": "a2", "type": "action", "data": {}},
        ],
        "edges": [
            {"source": "t1", "target": "a1"},
            {"source": "a1", "target": "a2"},
            {"source": "a2", "target": "a1"},
        ],
    }
    response = await client.post(
        "/api/v1/automations",
        headers=headers,
        json={
            "name": "Cyclic Flow",
            "initiative_id": initiative.id,
            "flow_data": cyclic_flow,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == AutomationsMessages.INVALID_FLOW_GRAPH


@pytest.mark.integration
async def test_list_flows(client: AsyncClient, session: AsyncSession):
    """Admin can list flows for an initiative."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)

    await _create_flow_via_api(client, headers, initiative.id, name="Flow A")
    await _create_flow_via_api(client, headers, initiative.id, name="Flow B")

    response = await client.get(
        "/api/v1/automations",
        headers=headers,
        params={"initiative_id": initiative.id},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] == 2
    assert len(data["items"]) == 2
    # List items should NOT include flow_data
    assert "flow_data" not in data["items"][0]
    names = {item["name"] for item in data["items"]}
    assert "Flow A" in names
    assert "Flow B" in names


@pytest.mark.integration
async def test_list_flows_pagination(client: AsyncClient, session: AsyncSession):
    """List endpoint respects pagination parameters."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)

    for i in range(3):
        await _create_flow_via_api(client, headers, initiative.id, name=f"Flow {i}")

    response = await client.get(
        "/api/v1/automations",
        headers=headers,
        params={"initiative_id": initiative.id, "page": 1, "page_size": 2},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] == 3
    assert len(data["items"]) == 2
    assert data["has_next"] is True
    assert data["page"] == 1


@pytest.mark.integration
async def test_get_flow(client: AsyncClient, session: AsyncSession):
    """Admin can get a single flow with full flow_data."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)

    created = await _create_flow_via_api(client, headers, initiative.id, name="Detail Flow")

    response = await client.get(
        f"/api/v1/automations/{created['id']}",
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == created["id"]
    assert data["name"] == "Detail Flow"
    assert data["flow_data"] == VALID_FLOW_DATA


@pytest.mark.integration
async def test_get_flow_not_found(client: AsyncClient, session: AsyncSession):
    """Getting a non-existent flow returns 404."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)

    response = await client.get(
        "/api/v1/automations/99999",
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == AutomationsMessages.FLOW_NOT_FOUND


@pytest.mark.integration
async def test_update_flow(client: AsyncClient, session: AsyncSession):
    """Admin can update a flow's name and enabled status."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)

    created = await _create_flow_via_api(client, headers, initiative.id)

    response = await client.put(
        f"/api/v1/automations/{created['id']}",
        headers=headers,
        json={"name": "Updated Name", "enabled": True},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Name"
    assert data["enabled"] is True


@pytest.mark.integration
async def test_update_flow_validates_graph(client: AsyncClient, session: AsyncSession):
    """Updating flow_data triggers graph validation."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)

    created = await _create_flow_via_api(client, headers, initiative.id)

    bad_flow = {"nodes": [], "edges": []}
    response = await client.put(
        f"/api/v1/automations/{created['id']}",
        headers=headers,
        json={"flow_data": bad_flow},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == AutomationsMessages.INVALID_FLOW_GRAPH


@pytest.mark.integration
async def test_delete_flow(client: AsyncClient, session: AsyncSession):
    """Admin can delete a flow."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)

    created = await _create_flow_via_api(client, headers, initiative.id)

    response = await client.delete(
        f"/api/v1/automations/{created['id']}",
        headers=headers,
    )

    assert response.status_code == 204

    # Confirm it's gone
    response = await client.get(
        f"/api/v1/automations/{created['id']}",
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_automations_disabled_initiative(client: AsyncClient, session: AsyncSession):
    """Listing flows for an initiative with automations_enabled=False returns 403."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(
        session, guild, admin,
        name="No Automations",
        automations_enabled=False,
    )
    headers = get_guild_headers(guild, admin)

    response = await client.get(
        "/api/v1/automations",
        headers=headers,
        params={"initiative_id": initiative.id},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == AutomationsMessages.FEATURE_DISABLED


@pytest.mark.integration
async def test_automations_infra_disabled(client: AsyncClient, session: AsyncSession):
    """When ENABLE_AUTOMATIONS is False, all endpoints return 403."""
    settings.ENABLE_AUTOMATIONS = False

    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)

    response = await client.get(
        "/api/v1/automations",
        headers=headers,
        params={"initiative_id": initiative.id},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == AutomationsMessages.INFRA_FEATURE_DISABLED


# ---------------------------------------------------------------------------
# Run history (read-only, no runs in DB yet — verify 404 / empty list)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_runs_empty(client: AsyncClient, session: AsyncSession):
    """Listing runs for a flow with no runs returns an empty list."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)

    created = await _create_flow_via_api(client, headers, initiative.id)

    response = await client.get(
        f"/api/v1/automations/{created['id']}/runs",
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] == 0
    assert data["items"] == []
    assert data["has_next"] is False


@pytest.mark.integration
async def test_get_run_not_found(client: AsyncClient, session: AsyncSession):
    """Getting a non-existent run returns 404."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)

    response = await client.get(
        "/api/v1/automations/runs/99999",
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == AutomationsMessages.RUN_NOT_FOUND


# ---------------------------------------------------------------------------
# Graph validation unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_validate_flow_graph_valid():
    """A valid flow graph produces no warnings."""
    from app.schemas.automation import validate_flow_graph

    warnings = validate_flow_graph(VALID_FLOW_DATA)
    assert warnings == []


@pytest.mark.unit
def test_validate_flow_graph_no_trigger():
    """A graph without a trigger node produces a warning."""
    from app.schemas.automation import validate_flow_graph

    flow = {
        "nodes": [{"id": "a1", "type": "action"}],
        "edges": [],
    }
    warnings = validate_flow_graph(flow)
    assert any("trigger" in w.lower() for w in warnings)


@pytest.mark.unit
def test_validate_flow_graph_multiple_triggers():
    """A graph with multiple trigger nodes produces a warning."""
    from app.schemas.automation import validate_flow_graph

    flow = {
        "nodes": [
            {"id": "t1", "type": "trigger"},
            {"id": "t2", "type": "trigger"},
        ],
        "edges": [],
    }
    warnings = validate_flow_graph(flow)
    assert any("2 trigger" in w for w in warnings)


@pytest.mark.unit
def test_validate_flow_graph_cycle():
    """A graph with a cycle produces a warning."""
    from app.schemas.automation import validate_flow_graph

    flow = {
        "nodes": [
            {"id": "t1", "type": "trigger"},
            {"id": "a1", "type": "action"},
            {"id": "a2", "type": "action"},
        ],
        "edges": [
            {"source": "t1", "target": "a1"},
            {"source": "a1", "target": "a2"},
            {"source": "a2", "target": "a1"},
        ],
    }
    warnings = validate_flow_graph(flow)
    assert any("cycle" in w.lower() for w in warnings)


@pytest.mark.unit
def test_validate_flow_graph_empty_nodes():
    """An empty nodes list produces a warning."""
    from app.schemas.automation import validate_flow_graph

    flow = {"nodes": [], "edges": []}
    warnings = validate_flow_graph(flow)
    assert any("at least one node" in w.lower() for w in warnings)
