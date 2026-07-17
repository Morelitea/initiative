"""
Integration tests for queue endpoints — CRUD, items, turns, permissions.
"""

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.models.tenant.initiative import InitiativeRoleModel
from app.testing import Actor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_queue_via_api(
    client: AsyncClient,
    actor: Actor,
    name: str = "Test Queue",
) -> dict:
    """Create a queue via API and return the response data."""
    response = await client.post(
        actor.g("/queues/"),
        headers=actor.headers,
        json={"name": name, "initiative_id": actor.initiative.id},
    )
    assert response.status_code == 201
    return response.json()


async def _add_item_via_api(
    client: AsyncClient,
    actor: Actor,
    queue_id: int,
    label: str,
    position: float = 0,
) -> dict:
    """Add an item to a queue via API."""
    response = await client.post(
        actor.g(f"/queues/{queue_id}/items"),
        headers=actor.headers,
        json={"label": label, "position": position},
    )
    assert response.status_code == 201
    return response.json()


# ---------------------------------------------------------------------------
# Queue CRUD
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_queue(client: AsyncClient, acting_user):
    """PM can create a queue."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)

    response = await client.post(
        a.g("/queues/"),
        headers=a.headers,
        json={
            "name": "Initiative Order",
            "description": "Turn tracker",
            "initiative_id": a.initiative.id,
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Initiative Order"
    assert data["description"] == "Turn tracker"
    assert data["initiative_id"] == a.initiative.id
    assert data["created_by_id"] == a.user.id
    assert data["is_active"] is False
    assert data["current_round"] == 1


@pytest.mark.integration
async def test_create_queue_non_pm_forbidden(client: AsyncClient, acting_user):
    """Non-PM member cannot create a queue (unless role allows it)."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )

    response = await client.post(
        member.g("/queues/"),
        headers=member.headers,
        json={
            "name": "Forbidden Queue",
            "initiative_id": admin.initiative.id,
        },
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_list_queues(client: AsyncClient, acting_user):
    """Admin can list queues."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _create_queue_via_api(client, a, "Listed Queue")

    response = await client.get(a.g("/queues/"), headers=a.headers)

    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] >= 1
    names = [q["name"] for q in data["items"]]
    assert "Listed Queue" in names


@pytest.mark.integration
async def test_get_queue(client: AsyncClient, acting_user):
    """Owner can fetch queue details."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data = await _create_queue_via_api(client, a)

    response = await client.get(a.g(f"/queues/{queue_data['id']}"), headers=a.headers)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == queue_data["id"]
    assert data["my_permission_level"] == "owner"


@pytest.mark.integration
async def test_update_queue(client: AsyncClient, acting_user):
    """Owner can update queue name/description."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data = await _create_queue_via_api(client, a)

    response = await client.patch(
        a.g(f"/queues/{queue_data['id']}"),
        headers=a.headers,
        json={"name": "Updated Name", "description": "Updated desc"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Name"
    assert data["description"] == "Updated desc"


@pytest.mark.integration
async def test_delete_queue(client: AsyncClient, acting_user):
    """Owner can delete a queue."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data = await _create_queue_via_api(client, a)

    response = await client.delete(
        a.g(f"/queues/{queue_data['id']}"), headers=a.headers
    )
    assert response.status_code == 204

    # Verify gone
    response = await client.get(a.g(f"/queues/{queue_data['id']}"), headers=a.headers)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Queue Items
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_add_queue_item(client: AsyncClient, acting_user):
    """Owner can add an item to a queue."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data = await _create_queue_via_api(client, a)

    response = await client.post(
        a.g(f"/queues/{queue_data['id']}/items"),
        headers=a.headers,
        json={"label": "Player 1", "position": 15, "color": "#FF0000"},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["label"] == "Player 1"
    assert data["position"] == 15
    assert data["color"] == "#FF0000"


@pytest.mark.integration
async def test_update_queue_item(client: AsyncClient, acting_user):
    """Owner can update an item."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data = await _create_queue_via_api(client, a)
    item_data = await _add_item_via_api(client, a, queue_data["id"], "Original")

    response = await client.patch(
        a.g(f"/queues/{queue_data['id']}/items/{item_data['id']}"),
        headers=a.headers,
        json={"label": "Renamed", "position": 5},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["label"] == "Renamed"
    assert data["position"] == 5


@pytest.mark.integration
async def test_delete_queue_item(client: AsyncClient, acting_user):
    """Owner can delete an item."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data = await _create_queue_via_api(client, a)
    item_data = await _add_item_via_api(client, a, queue_data["id"], "To Delete")

    response = await client.delete(
        a.g(f"/queues/{queue_data['id']}/items/{item_data['id']}"),
        headers=a.headers,
    )
    assert response.status_code == 204


@pytest.mark.integration
async def test_reorder_queue_items(client: AsyncClient, acting_user):
    """Owner can bulk-reorder items."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data = await _create_queue_via_api(client, a)
    item_a = await _add_item_via_api(client, a, queue_data["id"], "A", position=1)
    item_b = await _add_item_via_api(client, a, queue_data["id"], "B", position=2)

    response = await client.put(
        a.g(f"/queues/{queue_data['id']}/items/reorder"),
        headers=a.headers,
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
async def test_fractional_positions(client: AsyncClient, acting_user):
    """Items with the same integer initiative can be split by a fractional position."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data = await _create_queue_via_api(client, a)
    item_a = await _add_item_via_api(client, a, queue_data["id"], "A", position=10)
    await _add_item_via_api(client, a, queue_data["id"], "B", position=10)

    # Drop C between A and B without renumbering either.
    response = await client.post(
        a.g(f"/queues/{queue_data['id']}/items"),
        headers=a.headers,
        json={"label": "C", "position": 10.5},
    )
    assert response.status_code == 201
    assert response.json()["position"] == 10.5

    # Persisted precision survives a round-trip.
    update = await client.patch(
        a.g(f"/queues/{queue_data['id']}/items/{item_a['id']}"),
        headers=a.headers,
        json={"position": 10.25},
    )
    assert update.status_code == 200
    assert update.json()["position"] == 10.25

    # Positions are now C=10.5, A=10.25, B=10. Turn order must respect the
    # fractional ordering (descending), not collapse to the shared integer.
    start = await client.post(
        a.g(f"/queues/{queue_data['id']}/start"), headers=a.headers
    )
    assert start.status_code == 200
    assert start.json()["current_item"]["label"] == "C"

    second = await client.post(
        a.g(f"/queues/{queue_data['id']}/next"), headers=a.headers
    )
    assert second.status_code == 200
    assert second.json()["current_item"]["label"] == "A"

    third = await client.post(
        a.g(f"/queues/{queue_data['id']}/next"), headers=a.headers
    )
    assert third.status_code == 200
    assert third.json()["current_item"]["label"] == "B"


# ---------------------------------------------------------------------------
# Turn management
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_start_and_stop_queue(client: AsyncClient, acting_user):
    """Start activates the queue, stop deactivates it."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data = await _create_queue_via_api(client, a)
    await _add_item_via_api(client, a, queue_data["id"], "P1", position=10)

    # Start
    response = await client.post(
        a.g(f"/queues/{queue_data['id']}/start"), headers=a.headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["is_active"] is True
    assert data["current_item"] is not None

    # Stop
    response = await client.post(
        a.g(f"/queues/{queue_data['id']}/stop"), headers=a.headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["is_active"] is False


@pytest.mark.integration
async def test_advance_turn(client: AsyncClient, acting_user):
    """Advancing cycles through visible items."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data = await _create_queue_via_api(client, a)
    await _add_item_via_api(client, a, queue_data["id"], "A", position=10)
    await _add_item_via_api(client, a, queue_data["id"], "B", position=20)

    # Start
    await client.post(a.g(f"/queues/{queue_data['id']}/start"), headers=a.headers)

    # Advance
    response = await client.post(
        a.g(f"/queues/{queue_data['id']}/next"), headers=a.headers
    )
    assert response.status_code == 200


@pytest.mark.integration
async def test_reset_queue(client: AsyncClient, acting_user):
    """Reset resets round to 1 and sets current to first visible item."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data = await _create_queue_via_api(client, a)
    await _add_item_via_api(client, a, queue_data["id"], "P1", position=5)

    await client.post(a.g(f"/queues/{queue_data['id']}/start"), headers=a.headers)

    response = await client.post(
        a.g(f"/queues/{queue_data['id']}/reset"), headers=a.headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["current_round"] == 1
    assert data["current_item"] is not None


# ---------------------------------------------------------------------------
# Hold / release
# ---------------------------------------------------------------------------


async def _running_queue_with_abc(
    client: AsyncClient, actor: Actor
) -> tuple[dict, dict, dict, dict]:
    """Helper: queue with three items A(30), B(20), C(10), started; current=A."""
    queue_data = await _create_queue_via_api(client, actor)
    a = await _add_item_via_api(client, actor, queue_data["id"], "A", position=30)
    b = await _add_item_via_api(client, actor, queue_data["id"], "B", position=20)
    c = await _add_item_via_api(client, actor, queue_data["id"], "C", position=10)
    await client.post(
        actor.g(f"/queues/{queue_data['id']}/start"), headers=actor.headers
    )
    return queue_data, a, b, c


def _items_by_id(payload: dict) -> dict[int, dict]:
    return {item["id"]: item for item in payload["items"]}


@pytest.mark.integration
async def test_hold_current_records_round_and_advances(
    client: AsyncClient, acting_user
):
    """Hold the current item: held_at_round is set, current advances past it."""
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data, a, b, _c = await _running_queue_with_abc(client, actor)

    response = await client.post(
        actor.g(f"/queues/{queue_data['id']}/hold"), headers=actor.headers
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["current_item"]["id"] == b["id"]
    assert payload["current_round"] == 1
    by_id = _items_by_id(payload)
    assert by_id[a["id"]]["held_at_round"] == 1


@pytest.mark.integration
async def test_hold_only_item_clears_current(client: AsyncClient, acting_user):
    """Holding the last rotation-eligible item leaves current_item = None."""
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data = await _create_queue_via_api(client, actor)
    a = await _add_item_via_api(client, actor, queue_data["id"], "Solo", position=10)
    await client.post(
        actor.g(f"/queues/{queue_data['id']}/start"), headers=actor.headers
    )

    response = await client.post(
        actor.g(f"/queues/{queue_data['id']}/hold"), headers=actor.headers
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["current_item"] is None
    assert _items_by_id(payload)[a["id"]]["held_at_round"] == 1


@pytest.mark.integration
async def test_advance_auto_releases_at_natural_slot(client: AsyncClient, acting_user):
    """Held A returns to current when round 2 reaches A's position-desc slot."""
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data, a, b, c = await _running_queue_with_abc(client, actor)

    # Hold A; current is now B in round 1.
    await client.post(
        actor.g(f"/queues/{queue_data['id']}/hold"), headers=actor.headers
    )
    # B -> C, still round 1.
    after_bc = (
        await client.post(
            actor.g(f"/queues/{queue_data['id']}/next"), headers=actor.headers
        )
    ).json()
    assert after_bc["current_item"]["id"] == c["id"]
    assert after_bc["current_round"] == 1
    # C -> wraps to round 2; A is the next visible position-desc slot and is
    # auto-released because held_at_round (1) < new round (2).
    after_wrap = (
        await client.post(
            actor.g(f"/queues/{queue_data['id']}/next"), headers=actor.headers
        )
    ).json()
    assert after_wrap["current_item"]["id"] == a["id"]
    assert after_wrap["current_round"] == 2
    assert _items_by_id(after_wrap)[a["id"]]["held_at_round"] is None
    # B and C are untouched.
    assert _items_by_id(after_wrap)[b["id"]]["held_at_round"] is None


@pytest.mark.integration
async def test_release_clears_hold_without_rewinding(client: AsyncClient, acting_user):
    """Release clears `held_at_round` but leaves the current pointer alone.

    The released item rejoins the rotation; whoever was currently up stays up
    so the rotation doesn't double-act items that already took their turn.
    """
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data, a, b, _c = await _running_queue_with_abc(client, actor)

    # Hold A; current is B.
    await client.post(
        actor.g(f"/queues/{queue_data['id']}/hold"), headers=actor.headers
    )
    response = await client.post(
        actor.g(f"/queues/{queue_data['id']}/release/{a['id']}"),
        headers=actor.headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["current_item"]["id"] == b["id"]  # unchanged
    assert payload["current_round"] == 1
    assert _items_by_id(payload)[a["id"]]["held_at_round"] is None


@pytest.mark.integration
async def test_release_with_reposition_lifts_target_above_current(
    client: AsyncClient, acting_user
):
    """Reposition places the released item above current and makes them act now."""
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data, a, b, c = await _running_queue_with_abc(client, actor)

    # Hold A (pos 30) on its turn → current becomes B (pos 20). After hold,
    # the only items above B in the rotation are... none (A is held, so B is
    # effectively the top of the active rotation).
    await client.post(
        actor.g(f"/queues/{queue_data['id']}/hold"), headers=actor.headers
    )
    # Release A with reposition: A acts now (becomes current), and its new
    # position drops just above B (which was current).
    response = await client.post(
        actor.g(f"/queues/{queue_data['id']}/release/{a['id']}"),
        headers=actor.headers,
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
        await client.post(
            actor.g(f"/queues/{queue_data['id']}/next"), headers=actor.headers
        )
    ).json()
    assert after_next["current_item"]["id"] == b["id"]


@pytest.mark.integration
async def test_release_with_reposition_between_current_and_higher(
    client: AsyncClient, acting_user
):
    """When other active items sit above current, target lands between them."""
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data = await _create_queue_via_api(client, actor)
    a = await _add_item_via_api(client, actor, queue_data["id"], "A", position=30)
    b = await _add_item_via_api(client, actor, queue_data["id"], "B", position=20)
    c = await _add_item_via_api(client, actor, queue_data["id"], "C", position=10)
    await client.post(
        actor.g(f"/queues/{queue_data['id']}/start"), headers=actor.headers
    )
    # Advance to B (current goes A → B). Then hold B → current becomes C.
    await client.post(
        actor.g(f"/queues/{queue_data['id']}/next"), headers=actor.headers
    )
    await client.post(
        actor.g(f"/queues/{queue_data['id']}/hold"), headers=actor.headers
    )
    # Now A (pos 30) is active and above C (current, pos 10). Release B with
    # reposition: B's new position should land between C (10) and A (30) — the
    # midpoint is 20.
    response = await client.post(
        actor.g(f"/queues/{queue_data['id']}/release/{b['id']}"),
        headers=actor.headers,
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
    client: AsyncClient, acting_user
):
    """Calling release with an empty body keeps the original behavior (no reposition)."""
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data, a, _b, _c = await _running_queue_with_abc(client, actor)

    original_position = a["position"]
    await client.post(
        actor.g(f"/queues/{queue_data['id']}/hold"), headers=actor.headers
    )
    response = await client.post(
        actor.g(f"/queues/{queue_data['id']}/release/{a['id']}"),
        headers=actor.headers,
        json={},
    )
    assert response.status_code == 200
    by_id = _items_by_id(response.json())
    assert by_id[a["id"]]["position"] == original_position


@pytest.mark.integration
async def test_release_while_stopped(client: AsyncClient, acting_user):
    """Release works when the queue is stopped; is_active is preserved."""
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data, a, b, _c = await _running_queue_with_abc(client, actor)

    await client.post(
        actor.g(f"/queues/{queue_data['id']}/hold"), headers=actor.headers
    )
    await client.post(
        actor.g(f"/queues/{queue_data['id']}/stop"), headers=actor.headers
    )
    response = await client.post(
        actor.g(f"/queues/{queue_data['id']}/release/{a['id']}"),
        headers=actor.headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_active"] is False
    # Current pointer is whatever it was when we stopped — release doesn't
    # rewind it.
    assert payload["current_item"]["id"] == b["id"]
    assert _items_by_id(payload)[a["id"]]["held_at_round"] is None


@pytest.mark.integration
async def test_set_active_clears_held(client: AsyncClient, acting_user):
    """set-active on a held item also clears its held_at_round."""
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data, a, _b, _c = await _running_queue_with_abc(client, actor)

    await client.post(
        actor.g(f"/queues/{queue_data['id']}/hold"), headers=actor.headers
    )
    response = await client.post(
        actor.g(f"/queues/{queue_data['id']}/set-active/{a['id']}"),
        headers=actor.headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["current_item"]["id"] == a["id"]
    assert _items_by_id(payload)[a["id"]]["held_at_round"] is None


@pytest.mark.integration
async def test_previous_skips_held_no_auto_release(client: AsyncClient, acting_user):
    """Previous never lands on a held item, and never clears its hold."""
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data, a, _b, c = await _running_queue_with_abc(client, actor)

    # Hold A (round 1, current was A); current becomes B.
    await client.post(
        actor.g(f"/queues/{queue_data['id']}/hold"), headers=actor.headers
    )
    # Previous from B should wrap (B is first in the active rotation now) to C
    # in round 0 → clamped to round 1.
    response = await client.post(
        actor.g(f"/queues/{queue_data['id']}/previous"), headers=actor.headers
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["current_item"]["id"] == c["id"]
    # A is still held.
    assert _items_by_id(payload)[a["id"]]["held_at_round"] == 1


@pytest.mark.integration
async def test_reset_preserves_held(client: AsyncClient, acting_user):
    """Reset jumps to the highest un-held item; held items stay held."""
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data, a, b, _c = await _running_queue_with_abc(client, actor)

    await client.post(
        actor.g(f"/queues/{queue_data['id']}/hold"), headers=actor.headers
    )
    response = await client.post(
        actor.g(f"/queues/{queue_data['id']}/reset"), headers=actor.headers
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["current_round"] == 1
    assert payload["current_item"]["id"] == b["id"]
    assert _items_by_id(payload)[a["id"]]["held_at_round"] == 1


@pytest.mark.integration
async def test_hold_no_current_item(client: AsyncClient, acting_user):
    """Hold with no current item returns 400 NO_CURRENT_ITEM."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data = await _create_queue_via_api(client, a)
    await _add_item_via_api(client, a, queue_data["id"], "Solo", position=10)
    # Don't start: current_item_id stays None.

    response = await client.post(
        a.g(f"/queues/{queue_data['id']}/hold"), headers=a.headers
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "QUEUE_NO_CURRENT_ITEM"


@pytest.mark.integration
async def test_release_unheld_item_returns_400(client: AsyncClient, acting_user):
    """Calling release on an item that isn't held returns ITEM_NOT_HELD."""
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data, a, _b, _c = await _running_queue_with_abc(client, actor)

    response = await client.post(
        actor.g(f"/queues/{queue_data['id']}/release/{a['id']}"),
        headers=actor.headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "QUEUE_ITEM_NOT_HELD"


@pytest.mark.integration
async def test_hold_requires_write_access(client: AsyncClient, acting_user):
    """Members without write permission can't hold."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    queue_data, _a, _b, _c = await _running_queue_with_abc(client, admin)

    response = await client.post(
        member.g(f"/queues/{queue_data['id']}/hold"), headers=member.headers
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Permissions (DAC)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_set_queue_grants(client: AsyncClient, acting_user):
    """Owner can set user grants on a queue via the unified grants endpoint."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    queue_data = await _create_queue_via_api(client, admin)

    response = await client.put(
        admin.g(f"/queues/{queue_data['id']}/grants"),
        headers=admin.headers,
        json=[{"user_id": member.user.id, "level": "write"}],
    )

    assert response.status_code == 200
    data = response.json()
    member_grants = [
        g
        for g in data["grants"]
        if g["user_id"] == member.user.id and g["level"] == "write"
    ]
    assert len(member_grants) == 1


@pytest.mark.integration
async def test_set_queue_role_grants(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Owner can set role grants on a queue via the unified grants endpoint."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data = await _create_queue_via_api(client, a)

    # Find the member role
    result = await session.exec(
        select(InitiativeRoleModel).where(
            InitiativeRoleModel.initiative_id == a.initiative.id,
            InitiativeRoleModel.name == "member",
        )
    )
    member_role = result.one()

    response = await client.put(
        a.g(f"/queues/{queue_data['id']}/grants"),
        headers=a.headers,
        json=[{"role_id": member_role.id, "level": "read"}],
    )

    assert response.status_code == 200
    data = response.json()
    role_grants = [
        g
        for g in data["grants"]
        if g["role_id"] == member_role.id and g["level"] == "read"
    ]
    assert len(role_grants) == 1


@pytest.mark.integration
async def test_member_with_read_can_view_queue(client: AsyncClient, acting_user):
    """Member with read permission can view but not modify."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    queue_data = await _create_queue_via_api(client, admin)

    # Grant read to member
    await client.put(
        admin.g(f"/queues/{queue_data['id']}/grants"),
        headers=admin.headers,
        json=[{"user_id": member.user.id, "level": "read"}],
    )

    # Can read
    response = await client.get(
        member.g(f"/queues/{queue_data['id']}"), headers=member.headers
    )
    assert response.status_code == 200

    # Cannot update
    response = await client.patch(
        member.g(f"/queues/{queue_data['id']}"),
        headers=member.headers,
        json={"name": "Hacked"},
    )
    assert response.status_code == 403


@pytest.mark.integration
async def test_member_without_permission_cannot_view(client: AsyncClient, acting_user):
    """Member with no permission cannot access the queue."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    queue_data = await _create_queue_via_api(client, admin)
    # New queues default to all-members Viewer; restrict to owner-only so a member
    # without a grant is genuinely denied.
    restrict = await client.put(
        admin.g(f"/queues/{queue_data['id']}/grants"),
        headers=admin.headers,
        json=[],
    )
    assert restrict.status_code == 200

    response = await client.get(
        member.g(f"/queues/{queue_data['id']}"), headers=member.headers
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Item associations (tags, documents, tasks)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_set_queue_item_tags(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Owner can set tags on a queue item."""
    from app.testing import create_tag

    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue_data = await _create_queue_via_api(client, a)
    item_data = await _add_item_via_api(client, a, queue_data["id"], "Tagged")

    # Create a tag
    tag = await create_tag(session, a.guild, name="Priority")

    response = await client.put(
        a.g(f"/queues/{queue_data['id']}/items/{item_data['id']}/tags"),
        headers=a.headers,
        json={"tag_ids": [tag.id]},
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["tags"]) == 1
    assert data["tags"][0]["id"] == tag.id


@pytest.mark.integration
async def test_create_queue_with_grants(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Create a queue with inline role and user grants."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )

    result = await session.exec(
        select(InitiativeRoleModel).where(
            InitiativeRoleModel.initiative_id == admin.initiative.id,
            InitiativeRoleModel.name == "member",
        )
    )
    member_role = result.one()

    response = await client.post(
        admin.g("/queues/"),
        headers=admin.headers,
        json={
            "name": "With Perms",
            "initiative_id": admin.initiative.id,
            "grants": [
                {"role_id": member_role.id, "level": "read"},
                {"user_id": member.user.id, "level": "write"},
            ],
        },
    )

    assert response.status_code == 201
    data = response.json()
    role_grants = [
        g
        for g in data["grants"]
        if g["role_id"] == member_role.id and g["user_id"] is None
    ]
    assert len(role_grants) == 1
    user_grants = [
        g
        for g in data["grants"]
        if g["user_id"] == member.user.id and g["level"] == "write"
    ]
    assert len(user_grants) == 1


@pytest.mark.integration
async def test_delete_queue_still_emits_queue_deleted(
    client: AsyncClient, acting_user, monkeypatch
):
    """Deleting a queue must still emit ``queue_deleted``. Regression: the queue
    is soft-deleted before _emit_queue runs, so its fallback guild lookup is
    hidden by the global deleted_at IS NULL filter — the delete path must pass
    guild_id explicitly or the event is silently dropped."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    queue = await _create_queue_via_api(client, a)

    from app.services import stream_authz

    emitted: list[tuple] = []

    async def _record(guild_id, resource_type, resource_id, event_type, data):
        emitted.append((guild_id, resource_type, resource_id, event_type))

    monkeypatch.setattr(stream_authz.authority, "emit", _record)

    resp = await client.delete(a.g(f"/queues/{queue['id']}"), headers=a.headers)
    assert resp.status_code == 204, resp.text
    assert (a.guild.id, "queue", queue["id"], "queue_deleted") in emitted
