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
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    initiative = await create_initiative(session, guild, admin, name="Test Initiative")
    return admin, guild, initiative


async def _setup_with_member(session: AsyncSession):
    """Create admin + regular member with guild/initiative membership."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    member = await create_user(session, email="member@example.com")
    await create_guild_membership(session, user=member, guild=guild)
    await create_initiative_member(session, initiative, member, role_name="member")
    return admin, member, guild, initiative


async def _create_queue_via_api(
    client: AsyncClient, headers: dict, initiative_id: int, name: str = "Test Queue"
) -> dict:
    """Create a queue via API and return the response data."""
    response = await client.post(
        "/api/v1/queues/",
        headers=headers,
        json={"name": name, "initiative_id": initiative_id},
    )
    assert response.status_code == 201
    return response.json()


async def _add_item_via_api(
    client: AsyncClient, headers: dict, queue_id: int, label: str, position: float = 0
) -> dict:
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
async def test_create_queue_non_pm_forbidden(
    client: AsyncClient, session: AsyncSession
):
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

    response = await client.delete(
        f"/api/v1/queues/{queue_data['id']}", headers=headers
    )
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
        json={
            "items": [
                {"id": item_a["id"], "position": 20},
                {"id": item_b["id"], "position": 10},
            ]
        },
    )

    assert response.status_code == 200
    data = response.json()
    items_by_id = {i["id"]: i for i in data["items"]}
    assert items_by_id[item_a["id"]]["position"] == 20
    assert items_by_id[item_b["id"]]["position"] == 10


@pytest.mark.integration
async def test_fractional_positions(client: AsyncClient, session: AsyncSession):
    """Items with the same integer initiative can be split by a fractional position."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data = await _create_queue_via_api(client, headers, initiative.id)
    item_a = await _add_item_via_api(
        client, headers, queue_data["id"], "A", position=10
    )
    await _add_item_via_api(client, headers, queue_data["id"], "B", position=10)

    # Drop C between A and B without renumbering either.
    response = await client.post(
        f"/api/v1/queues/{queue_data['id']}/items",
        headers=headers,
        json={"label": "C", "position": 10.5},
    )
    assert response.status_code == 201
    assert response.json()["position"] == 10.5

    # Persisted precision survives a round-trip.
    update = await client.patch(
        f"/api/v1/queues/{queue_data['id']}/items/{item_a['id']}",
        headers=headers,
        json={"position": 10.25},
    )
    assert update.status_code == 200
    assert update.json()["position"] == 10.25

    # Positions are now C=10.5, A=10.25, B=10. Turn order must respect the
    # fractional ordering (descending), not collapse to the shared integer.
    start = await client.post(
        f"/api/v1/queues/{queue_data['id']}/start", headers=headers
    )
    assert start.status_code == 200
    assert start.json()["current_item"]["label"] == "C"

    second = await client.post(
        f"/api/v1/queues/{queue_data['id']}/next", headers=headers
    )
    assert second.status_code == 200
    assert second.json()["current_item"]["label"] == "A"

    third = await client.post(
        f"/api/v1/queues/{queue_data['id']}/next", headers=headers
    )
    assert third.status_code == 200
    assert third.json()["current_item"]["label"] == "B"


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
    response = await client.post(
        f"/api/v1/queues/{queue_data['id']}/start", headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["is_active"] is True
    assert data["current_item"] is not None

    # Stop
    response = await client.post(
        f"/api/v1/queues/{queue_data['id']}/stop", headers=headers
    )
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
    response = await client.post(
        f"/api/v1/queues/{queue_data['id']}/next", headers=headers
    )
    assert response.status_code == 200


@pytest.mark.integration
async def test_reset_queue(client: AsyncClient, session: AsyncSession):
    """Reset resets round to 1 and sets current to first visible item."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data = await _create_queue_via_api(client, headers, initiative.id)
    await _add_item_via_api(client, headers, queue_data["id"], "P1", position=5)

    await client.post(f"/api/v1/queues/{queue_data['id']}/start", headers=headers)

    response = await client.post(
        f"/api/v1/queues/{queue_data['id']}/reset", headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["current_round"] == 1
    assert data["current_item"] is not None


# ---------------------------------------------------------------------------
# Hold / release
# ---------------------------------------------------------------------------


async def _running_queue_with_abc(
    client: AsyncClient, headers: dict, initiative_id: int
) -> tuple[dict, dict, dict, dict]:
    """Helper: queue with three items A(30), B(20), C(10), started; current=A."""
    queue_data = await _create_queue_via_api(client, headers, initiative_id)
    a = await _add_item_via_api(client, headers, queue_data["id"], "A", position=30)
    b = await _add_item_via_api(client, headers, queue_data["id"], "B", position=20)
    c = await _add_item_via_api(client, headers, queue_data["id"], "C", position=10)
    await client.post(f"/api/v1/queues/{queue_data['id']}/start", headers=headers)
    return queue_data, a, b, c


def _items_by_id(payload: dict) -> dict[int, dict]:
    return {item["id"]: item for item in payload["items"]}


@pytest.mark.integration
async def test_hold_current_records_round_and_advances(
    client: AsyncClient, session: AsyncSession
):
    """Hold the current item: held_at_round is set, current advances past it."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data, a, b, _c = await _running_queue_with_abc(client, headers, initiative.id)

    response = await client.post(
        f"/api/v1/queues/{queue_data['id']}/hold", headers=headers
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["current_item"]["id"] == b["id"]
    assert payload["current_round"] == 1
    by_id = _items_by_id(payload)
    assert by_id[a["id"]]["held_at_round"] == 1


@pytest.mark.integration
async def test_hold_only_item_clears_current(
    client: AsyncClient, session: AsyncSession
):
    """Holding the last rotation-eligible item leaves current_item = None."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data = await _create_queue_via_api(client, headers, initiative.id)
    a = await _add_item_via_api(client, headers, queue_data["id"], "Solo", position=10)
    await client.post(f"/api/v1/queues/{queue_data['id']}/start", headers=headers)

    response = await client.post(
        f"/api/v1/queues/{queue_data['id']}/hold", headers=headers
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["current_item"] is None
    assert _items_by_id(payload)[a["id"]]["held_at_round"] == 1


@pytest.mark.integration
async def test_advance_auto_releases_at_natural_slot(
    client: AsyncClient, session: AsyncSession
):
    """Held A returns to current when round 2 reaches A's position-desc slot."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data, a, b, c = await _running_queue_with_abc(client, headers, initiative.id)

    # Hold A; current is now B in round 1.
    await client.post(f"/api/v1/queues/{queue_data['id']}/hold", headers=headers)
    # B -> C, still round 1.
    after_bc = (
        await client.post(f"/api/v1/queues/{queue_data['id']}/next", headers=headers)
    ).json()
    assert after_bc["current_item"]["id"] == c["id"]
    assert after_bc["current_round"] == 1
    # C -> wraps to round 2; A is the next visible position-desc slot and is
    # auto-released because held_at_round (1) < new round (2).
    after_wrap = (
        await client.post(f"/api/v1/queues/{queue_data['id']}/next", headers=headers)
    ).json()
    assert after_wrap["current_item"]["id"] == a["id"]
    assert after_wrap["current_round"] == 2
    assert _items_by_id(after_wrap)[a["id"]]["held_at_round"] is None
    # B and C are untouched.
    assert _items_by_id(after_wrap)[b["id"]]["held_at_round"] is None


@pytest.mark.integration
async def test_release_clears_hold_without_rewinding(
    client: AsyncClient, session: AsyncSession
):
    """Release clears `held_at_round` but leaves the current pointer alone.

    The released item rejoins the rotation; whoever was currently up stays up
    so the rotation doesn't double-act items that already took their turn.
    """
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data, a, b, _c = await _running_queue_with_abc(client, headers, initiative.id)

    # Hold A; current is B.
    await client.post(f"/api/v1/queues/{queue_data['id']}/hold", headers=headers)
    response = await client.post(
        f"/api/v1/queues/{queue_data['id']}/release/{a['id']}", headers=headers
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["current_item"]["id"] == b["id"]  # unchanged
    assert payload["current_round"] == 1
    assert _items_by_id(payload)[a["id"]]["held_at_round"] is None


@pytest.mark.integration
async def test_release_with_reposition_lifts_target_above_current(
    client: AsyncClient, session: AsyncSession
):
    """Reposition places the released item above current and makes them act now."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data, a, b, c = await _running_queue_with_abc(client, headers, initiative.id)

    # Hold A (pos 30) on its turn → current becomes B (pos 20). After hold,
    # the only items above B in the rotation are... none (A is held, so B is
    # effectively the top of the active rotation).
    await client.post(f"/api/v1/queues/{queue_data['id']}/hold", headers=headers)
    # Release A with reposition: A acts now (becomes current), and its new
    # position drops just above B (which was current).
    response = await client.post(
        f"/api/v1/queues/{queue_data['id']}/release/{a['id']}",
        headers=headers,
        json={"reposition": True},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["current_item"]["id"] == a["id"]  # A is now current
    by_id = _items_by_id(payload)
    assert by_id[a["id"]]["held_at_round"] is None
    # A's new position is strictly above B's (and B is still above C).
    assert (
        by_id[a["id"]]["position"]
        > by_id[b["id"]]["position"]
        > by_id[c["id"]]["position"]
    )

    # Advancing from A goes to B next — A's elevated position persists.
    after_next = (
        await client.post(f"/api/v1/queues/{queue_data['id']}/next", headers=headers)
    ).json()
    assert after_next["current_item"]["id"] == b["id"]


@pytest.mark.integration
async def test_release_with_reposition_between_current_and_higher(
    client: AsyncClient, session: AsyncSession
):
    """When other active items sit above current, target lands between them."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data = await _create_queue_via_api(client, headers, initiative.id)
    a = await _add_item_via_api(client, headers, queue_data["id"], "A", position=30)
    b = await _add_item_via_api(client, headers, queue_data["id"], "B", position=20)
    c = await _add_item_via_api(client, headers, queue_data["id"], "C", position=10)
    await client.post(f"/api/v1/queues/{queue_data['id']}/start", headers=headers)
    # Advance to B (current goes A → B). Then hold B → current becomes C.
    await client.post(f"/api/v1/queues/{queue_data['id']}/next", headers=headers)
    await client.post(f"/api/v1/queues/{queue_data['id']}/hold", headers=headers)
    # Now A (pos 30) is active and above C (current, pos 10). Release B with
    # reposition: B's new position should land between C (10) and A (30) — the
    # midpoint is 20.
    response = await client.post(
        f"/api/v1/queues/{queue_data['id']}/release/{b['id']}",
        headers=headers,
        json={"reposition": True},
    )
    assert response.status_code == 200
    payload = response.json()
    by_id = _items_by_id(payload)
    assert by_id[b["id"]]["position"] == 20  # midpoint of 30 (A) and 10 (C)
    # B is now current — they're acting now, between A and C.
    assert payload["current_item"]["id"] == b["id"]
    # Sanity: A is still strictly above B, B above C.
    assert (
        by_id[a["id"]]["position"]
        > by_id[b["id"]]["position"]
        > by_id[c["id"]]["position"]
    )


@pytest.mark.integration
async def test_release_without_body_preserves_position(
    client: AsyncClient, session: AsyncSession
):
    """Calling release with an empty body keeps the original behavior (no reposition)."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data, a, _b, _c = await _running_queue_with_abc(
        client, headers, initiative.id
    )

    original_position = a["position"]
    await client.post(f"/api/v1/queues/{queue_data['id']}/hold", headers=headers)
    response = await client.post(
        f"/api/v1/queues/{queue_data['id']}/release/{a['id']}",
        headers=headers,
        json={},
    )
    assert response.status_code == 200
    by_id = _items_by_id(response.json())
    assert by_id[a["id"]]["position"] == original_position


@pytest.mark.integration
async def test_release_while_stopped(client: AsyncClient, session: AsyncSession):
    """Release works when the queue is stopped; is_active is preserved."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data, a, b, _c = await _running_queue_with_abc(client, headers, initiative.id)

    await client.post(f"/api/v1/queues/{queue_data['id']}/hold", headers=headers)
    await client.post(f"/api/v1/queues/{queue_data['id']}/stop", headers=headers)
    response = await client.post(
        f"/api/v1/queues/{queue_data['id']}/release/{a['id']}", headers=headers
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_active"] is False
    # Current pointer is whatever it was when we stopped — release doesn't
    # rewind it.
    assert payload["current_item"]["id"] == b["id"]
    assert _items_by_id(payload)[a["id"]]["held_at_round"] is None


@pytest.mark.integration
async def test_set_active_clears_held(client: AsyncClient, session: AsyncSession):
    """set-active on a held item also clears its held_at_round."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data, a, _b, _c = await _running_queue_with_abc(
        client, headers, initiative.id
    )

    await client.post(f"/api/v1/queues/{queue_data['id']}/hold", headers=headers)
    response = await client.post(
        f"/api/v1/queues/{queue_data['id']}/set-active/{a['id']}", headers=headers
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["current_item"]["id"] == a["id"]
    assert _items_by_id(payload)[a["id"]]["held_at_round"] is None


@pytest.mark.integration
async def test_previous_skips_held_no_auto_release(
    client: AsyncClient, session: AsyncSession
):
    """Previous never lands on a held item, and never clears its hold."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data, a, _b, c = await _running_queue_with_abc(client, headers, initiative.id)

    # Hold A (round 1, current was A); current becomes B.
    await client.post(f"/api/v1/queues/{queue_data['id']}/hold", headers=headers)
    # Previous from B should wrap (B is first in the active rotation now) to C
    # in round 0 → clamped to round 1.
    response = await client.post(
        f"/api/v1/queues/{queue_data['id']}/previous", headers=headers
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["current_item"]["id"] == c["id"]
    # A is still held.
    assert _items_by_id(payload)[a["id"]]["held_at_round"] == 1


@pytest.mark.integration
async def test_reset_preserves_held(client: AsyncClient, session: AsyncSession):
    """Reset jumps to the highest un-held item; held items stay held."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data, a, b, _c = await _running_queue_with_abc(client, headers, initiative.id)

    await client.post(f"/api/v1/queues/{queue_data['id']}/hold", headers=headers)
    response = await client.post(
        f"/api/v1/queues/{queue_data['id']}/reset", headers=headers
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["current_round"] == 1
    assert payload["current_item"]["id"] == b["id"]
    assert _items_by_id(payload)[a["id"]]["held_at_round"] == 1


@pytest.mark.integration
async def test_hold_no_current_item(client: AsyncClient, session: AsyncSession):
    """Hold with no current item returns 400 NO_CURRENT_ITEM."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data = await _create_queue_via_api(client, headers, initiative.id)
    await _add_item_via_api(client, headers, queue_data["id"], "Solo", position=10)
    # Don't start: current_item_id stays None.

    response = await client.post(
        f"/api/v1/queues/{queue_data['id']}/hold", headers=headers
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "QUEUE_NO_CURRENT_ITEM"


@pytest.mark.integration
async def test_release_unheld_item_returns_400(
    client: AsyncClient, session: AsyncSession
):
    """Calling release on an item that isn't held returns ITEM_NOT_HELD."""
    admin, guild, initiative = await _setup_guild_and_initiative(session)
    headers = get_guild_headers(guild, admin)
    queue_data, a, _b, _c = await _running_queue_with_abc(
        client, headers, initiative.id
    )

    response = await client.post(
        f"/api/v1/queues/{queue_data['id']}/release/{a['id']}", headers=headers
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "QUEUE_ITEM_NOT_HELD"


@pytest.mark.integration
async def test_hold_requires_write_access(client: AsyncClient, session: AsyncSession):
    """Members without write permission can't hold."""
    admin, member, guild, initiative = await _setup_with_member(session)
    admin_headers = get_guild_headers(guild, admin)
    member_headers = get_guild_headers(guild, member)
    queue_data, _a, _b, _c = await _running_queue_with_abc(
        client, admin_headers, initiative.id
    )

    response = await client.post(
        f"/api/v1/queues/{queue_data['id']}/hold", headers=member_headers
    )
    assert response.status_code == 403


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
async def test_member_with_read_can_view_queue(
    client: AsyncClient, session: AsyncSession
):
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
    response = await client.get(
        f"/api/v1/queues/{queue_data['id']}", headers=member_headers
    )
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
    response = await client.get(
        f"/api/v1/queues/{queue_data['id']}", headers=member_headers
    )
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
async def test_create_queue_with_permissions(
    client: AsyncClient, session: AsyncSession
):
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
            "role_permissions": [
                {"initiative_role_id": member_role.id, "level": "read"}
            ],
            "user_permissions": [{"user_id": member.id, "level": "write"}],
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert len(data["role_permissions"]) == 1
    user_perms = [p for p in data["permissions"] if p["user_id"] == member.id]
    assert len(user_perms) == 1
    assert user_perms[0]["level"] == "write"
