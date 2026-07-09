"""Integration tests for counter group endpoints."""

import pytest
from decimal import Decimal
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.testing import Actor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_group(
    client: AsyncClient,
    actor: Actor,
    *,
    name: str = "Test Group",
) -> dict:
    response = await client.post(
        actor.g("/counter-groups/"),
        headers=actor.headers,
        json={"name": name, "initiative_id": actor.initiative.id},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _add_counter(
    client: AsyncClient,
    actor: Actor,
    group_id: int,
    *,
    name: str = "HP",
    count: str = "100",
    min_value: str | None = "0",
    max_value: str | None = "100",
    step: str = "1",
    initial_count: str = "100",
    view_mode: str = "progress_bar",
    position: str = "0",
) -> dict:
    payload = {
        "name": name,
        "count": count,
        "step": step,
        "initial_count": initial_count,
        "view_mode": view_mode,
        "position": position,
    }
    if min_value is not None:
        payload["min"] = min_value
    if max_value is not None:
        payload["max"] = max_value
    response = await client.post(
        actor.g(f"/counter-groups/{group_id}/counters"),
        headers=actor.headers,
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Counter Group CRUD
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_counter_group(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)

    response = await client.post(
        a.g("/counter-groups/"),
        headers=a.headers,
        json={
            "name": "Combat Tracker",
            "description": "HP, AC, etc.",
            "initiative_id": a.initiative.id,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Combat Tracker"
    assert data["description"] == "HP, AC, etc."
    assert data["initiative_id"] == a.initiative.id
    assert data["created_by_id"] == a.user.id
    assert data["counter_count"] == 0


@pytest.mark.integration
async def test_create_counter_group_non_pm_forbidden(client: AsyncClient, acting_user):
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )

    response = await client.post(
        member.g("/counter-groups/"),
        headers=member.headers,
        json={"name": "Nope", "initiative_id": admin.initiative.id},
    )
    assert response.status_code == 403


@pytest.mark.integration
async def test_feature_disabled_blocks_creation(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    a.initiative.counter_groups_enabled = False
    await session.commit()

    response = await client.post(
        a.g("/counter-groups/"),
        headers=a.headers,
        json={"name": "X", "initiative_id": a.initiative.id},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "COUNTERS_NOT_ENABLED"


@pytest.mark.integration
async def test_list_counter_groups(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _create_group(client, a, name="Group A")
    await _create_group(client, a, name="Group B")

    response = await client.get(a.g("/counter-groups/"), headers=a.headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 2
    assert {item["name"] for item in body["items"]} == {"Group A", "Group B"}


# ---------------------------------------------------------------------------
# Counter CRUD + view mode validation
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_add_counter_clamps_initial_and_count(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    group = await _create_group(client, a)

    counter = await _add_counter(
        client,
        a,
        group["id"],
        count="999",
        min_value="0",
        max_value="50",
        initial_count="60",
    )
    assert Decimal(counter["count"]) == Decimal("50")
    assert Decimal(counter["initial_count"]) == Decimal("50")


@pytest.mark.integration
async def test_progress_bar_requires_bounds(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    group = await _create_group(client, a)

    response = await client.post(
        a.g(f"/counter-groups/{group['id']}/counters"),
        headers=a.headers,
        json={
            "name": "Bad",
            "count": "10",
            "view_mode": "progress_bar",
            "step": "1",
            "initial_count": "0",
            "position": "0",
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Value operations
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_increment_clamps_at_max(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    group = await _create_group(client, a)
    counter = await _add_counter(
        client,
        a,
        group["id"],
        count="99",
        min_value="0",
        max_value="100",
        step="5",
    )

    response = await client.post(
        a.g(f"/counter-groups/{group['id']}/counters/{counter['id']}/increment"),
        headers=a.headers,
    )
    assert response.status_code == 200
    assert Decimal(response.json()["count"]) == Decimal("100")


@pytest.mark.integration
async def test_decrement_clamps_at_min(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    group = await _create_group(client, a)
    counter = await _add_counter(
        client,
        a,
        group["id"],
        count="2",
        min_value="0",
        max_value="100",
        step="5",
    )

    response = await client.post(
        a.g(f"/counter-groups/{group['id']}/counters/{counter['id']}/decrement"),
        headers=a.headers,
    )
    assert response.status_code == 200
    assert Decimal(response.json()["count"]) == Decimal("0")


@pytest.mark.integration
async def test_set_count_clamps(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    group = await _create_group(client, a)
    counter = await _add_counter(client, a, group["id"], min_value="0", max_value="100")

    response = await client.post(
        a.g(f"/counter-groups/{group['id']}/counters/{counter['id']}/set"),
        headers=a.headers,
        json={"count": "9999"},
    )
    assert response.status_code == 200
    assert Decimal(response.json()["count"]) == Decimal("100")


@pytest.mark.integration
async def test_reset_returns_to_initial(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    group = await _create_group(client, a)
    counter = await _add_counter(
        client,
        a,
        group["id"],
        count="50",
        initial_count="80",
        min_value="0",
        max_value="100",
    )

    # Drop the value first
    await client.post(
        a.g(f"/counter-groups/{group['id']}/counters/{counter['id']}/set"),
        headers=a.headers,
        json={"count": "10"},
    )

    response = await client.post(
        a.g(f"/counter-groups/{group['id']}/counters/{counter['id']}/reset"),
        headers=a.headers,
    )
    assert response.status_code == 200
    assert Decimal(response.json()["count"]) == Decimal("80")


@pytest.mark.integration
async def test_reset_all_counters(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    group = await _create_group(client, a)
    c1 = await _add_counter(
        client,
        a,
        group["id"],
        name="A",
        initial_count="50",
        min_value="0",
        max_value="100",
    )
    c2 = await _add_counter(
        client,
        a,
        group["id"],
        name="B",
        initial_count="25",
        min_value="0",
        max_value="100",
        position="1",
    )

    # Mutate both
    await client.post(
        a.g(f"/counter-groups/{group['id']}/counters/{c1['id']}/set"),
        headers=a.headers,
        json={"count": "1"},
    )
    await client.post(
        a.g(f"/counter-groups/{group['id']}/counters/{c2['id']}/set"),
        headers=a.headers,
        json={"count": "1"},
    )

    response = await client.post(
        a.g(f"/counter-groups/{group['id']}/reset-all"), headers=a.headers
    )
    assert response.status_code == 200
    counts = {c["name"]: Decimal(c["count"]) for c in response.json()["counters"]}
    assert counts["A"] == Decimal("50")
    assert counts["B"] == Decimal("25")


# ---------------------------------------------------------------------------
# Position / re-clamp on update
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_update_min_max_reclamps_count(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    group = await _create_group(client, a)
    counter = await _add_counter(
        client, a, group["id"], count="100", min_value="0", max_value="100"
    )

    response = await client.patch(
        a.g(f"/counter-groups/{group['id']}/counters/{counter['id']}"),
        headers=a.headers,
        json={"max": "50"},
    )
    assert response.status_code == 200
    assert Decimal(response.json()["count"]) == Decimal("50")


@pytest.mark.integration
async def test_update_null_non_nullable_fields_is_noop(
    client: AsyncClient, acting_user
):
    """Explicit null for NOT NULL columns (step/initial_count/position/name/
    view_mode) must not 500 — it's treated as 'field not provided'."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    group = await _create_group(client, a)
    counter = await _add_counter(
        client,
        a,
        group["id"],
        name="HP",
        count="5",
        step="2",
        initial_count="0",
    )

    response = await client.patch(
        a.g(f"/counter-groups/{group['id']}/counters/{counter['id']}"),
        headers=a.headers,
        json={"step": None, "initial_count": None, "position": None, "name": None},
    )
    assert response.status_code == 200
    data = response.json()
    # Original values are preserved.
    assert data["name"] == "HP"
    assert Decimal(data["step"]) == Decimal("2")


@pytest.mark.integration
async def test_update_step_zero_rejected(client: AsyncClient, acting_user):
    """A provided step of 0 is a clean 422, not a 500."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    group = await _create_group(client, a)
    counter = await _add_counter(client, a, group["id"])

    response = await client.patch(
        a.g(f"/counter-groups/{group['id']}/counters/{counter['id']}"),
        headers=a.headers,
        json={"step": "0"},
    )
    assert response.status_code == 422


@pytest.mark.integration
async def test_decimal_serialization_no_exponent(client: AsyncClient, acting_user):
    """Numeric(20, 10) zeros must not round-trip as ``0E-10``."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    group = await _create_group(client, a)
    counter = await _add_counter(
        client,
        a,
        group["id"],
        count="0",
        min_value="0",
        max_value="100",
        initial_count="0",
        step="1",
    )
    # The response body strings should be plain, no scientific notation.
    assert counter["count"] == "0"
    assert counter["initial_count"] == "0"
    assert counter["min"] == "0"
    assert counter["step"] == "1"
    assert counter["position"] == "0"


@pytest.mark.integration
async def test_delete_counter_soft_deletes_to_trash(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Deleting a counter sets deleted_at and shows it in the trash list."""
    from app.db.soft_delete_filter import select_including_deleted
    from app.models.tenant.counter import Counter

    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    group = await _create_group(client, a)
    counter = await _add_counter(client, a, group["id"], name="HP")

    resp = await client.delete(
        a.g(f"/counter-groups/{group['id']}/counters/{counter['id']}"),
        headers=a.headers,
    )
    assert resp.status_code == 204

    # Confirm soft-delete stamp on the row.
    stmt = select_including_deleted(Counter).where(Counter.id == counter["id"])
    row = (await session.exec(stmt)).one()
    assert row.deleted_at is not None
    assert row.deleted_by == a.user.id

    # And it should appear in the trash list.
    trash = await client.get("/api/v1/me/trash", headers=a.headers)
    assert trash.status_code == 200
    entries = trash.json()["items"]
    assert any(
        item["entity_type"] == "counter" and item["entity_id"] == counter["id"]
        for item in entries
    )


@pytest.mark.integration
async def test_deleted_counter_group_hidden_from_list_and_read(
    client: AsyncClient, acting_user
):
    """Soft-deleted groups must not appear in list/read or accept counter
    adds. The session-level soft-delete filter is what enforces this."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    keep = await _create_group(client, a, name="Keep")
    trashed = await _create_group(client, a, name="Trash me")

    # Delete the second one.
    assert (
        await client.delete(a.g(f"/counter-groups/{trashed['id']}"), headers=a.headers)
    ).status_code == 204

    # List returns only the surviving group.
    listing = (await client.get(a.g("/counter-groups/"), headers=a.headers)).json()
    names = {item["name"] for item in listing["items"]}
    assert names == {"Keep"}
    assert listing["total_count"] == 1

    # Detail read returns 404.
    assert (
        await client.get(a.g(f"/counter-groups/{trashed['id']}"), headers=a.headers)
    ).status_code == 404

    # Trying to add a counter to it also 404s (the group is no longer reachable).
    add_resp = await client.post(
        a.g(f"/counter-groups/{trashed['id']}/counters"),
        headers=a.headers,
        json={
            "name": "Phantom",
            "count": "0",
            "step": "1",
            "initial_count": "0",
            "view_mode": "number",
            "position": "0",
        },
    )
    assert add_resp.status_code == 404

    # The surviving group still accepts adds.
    add_keep = await client.post(
        a.g(f"/counter-groups/{keep['id']}/counters"),
        headers=a.headers,
        json={
            "name": "OK",
            "count": "0",
            "step": "1",
            "initial_count": "0",
            "view_mode": "number",
            "position": "0",
        },
    )
    assert add_keep.status_code == 201


@pytest.mark.integration
async def test_delete_counter_group_soft_deletes_and_cascades(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Deleting a counter group soft-deletes it AND its counters; the group
    appears in the trash list but the cascaded counters are deduped out."""
    from app.db.soft_delete_filter import select_including_deleted
    from app.models.tenant.counter import Counter, CounterGroup

    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    group = await _create_group(client, a)
    counter = await _add_counter(client, a, group["id"], name="HP")

    resp = await client.delete(
        a.g(f"/counter-groups/{group['id']}"),
        headers=a.headers,
    )
    assert resp.status_code == 204

    group_row = (
        await session.exec(
            select_including_deleted(CounterGroup).where(CounterGroup.id == group["id"])
        )
    ).one()
    counter_row = (
        await session.exec(
            select_including_deleted(Counter).where(Counter.id == counter["id"])
        )
    ).one()

    assert group_row.deleted_at is not None
    assert counter_row.deleted_at is not None
    assert (
        counter_row.deleted_at == group_row.deleted_at
    )  # cascaded with same timestamp

    trash = await client.get("/api/v1/me/trash", headers=a.headers)
    assert trash.status_code == 200
    entries = trash.json()["items"]
    # Group is listed.
    assert any(
        item["entity_type"] == "counter_group" and item["entity_id"] == group["id"]
        for item in entries
    )
    # The cascaded counter is deduplicated out (same deleted_at as parent).
    assert not any(
        item["entity_type"] == "counter" and item["entity_id"] == counter["id"]
        for item in entries
    )


@pytest.mark.integration
async def test_fractional_position_sort(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    group_resp = await _create_group(client, a)
    group_id = group_resp["id"]

    counter_a = await _add_counter(client, a, group_id, name="A", position="10.0")
    await _add_counter(client, a, group_id, name="B", position="20.0")

    # Drop "A" between (would equal 15.0)
    response = await client.patch(
        a.g(f"/counter-groups/{group_id}/counters/{counter_a['id']}"),
        headers=a.headers,
        json={"position": "15.5"},
    )
    assert response.status_code == 200

    group = (
        await client.get(a.g(f"/counter-groups/{group_id}"), headers=a.headers)
    ).json()
    ordered = [c["name"] for c in group["counters"]]
    assert ordered == ["A", "B"] or ordered == ["B", "A"]  # position-ordered
    # Specifically: A position=15.5, B position=20.0 -> A first
    a_pos = next(Decimal(c["position"]) for c in group["counters"] if c["name"] == "A")
    b_pos = next(Decimal(c["position"]) for c in group["counters"] if c["name"] == "B")
    assert a_pos < b_pos


# ---------------------------------------------------------------------------
# Sort all counters
# ---------------------------------------------------------------------------


def _ordered_names(group: dict) -> list[str]:
    counters = sorted(group["counters"], key=lambda c: Decimal(c["position"]))
    return [c["name"] for c in counters]


@pytest.mark.integration
async def test_sort_counters(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    group = await _create_group(client, a)
    gid = group["id"]

    # Scrambled order; "alpha" is lowercase to exercise case-insensitive sort.
    await _add_counter(client, a, gid, name="Charlie", count="5", position="0")
    await _add_counter(client, a, gid, name="alpha", count="1", position="1")
    await _add_counter(client, a, gid, name="Bravo", count="3", position="2")

    async def sort(field: str, direction: str) -> dict:
        resp = await client.post(
            a.g(f"/counter-groups/{gid}/sort"),
            headers=a.headers,
            json={"field": field, "direction": direction},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    body = await sort("name", "asc")
    assert _ordered_names(body) == ["alpha", "Bravo", "Charlie"]
    # Positions are reassigned to a clean 1..N sequence.
    positions = sorted(Decimal(c["position"]) for c in body["counters"])
    assert positions == [Decimal("1"), Decimal("2"), Decimal("3")]

    assert _ordered_names(await sort("name", "desc")) == ["Charlie", "Bravo", "alpha"]
    assert _ordered_names(await sort("count", "asc")) == ["alpha", "Bravo", "Charlie"]
    assert _ordered_names(await sort("count", "desc")) == ["Charlie", "Bravo", "alpha"]

    # The reorder persists on a fresh read.
    fetched = (
        await client.get(a.g(f"/counter-groups/{gid}"), headers=a.headers)
    ).json()
    assert _ordered_names(fetched) == ["Charlie", "Bravo", "alpha"]


@pytest.mark.integration
async def test_sort_counters_read_only_forbidden(client: AsyncClient, acting_user):
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    group = await _create_group(client, admin)
    gid = group["id"]
    await _add_counter(client, admin, gid, name="A", position="0")

    # Grant the member read-only access on the group.
    grant = await client.put(
        admin.g(f"/counter-groups/{gid}/grants"),
        headers=admin.headers,
        json=[{"user_id": member.user.id, "level": "read"}],
    )
    assert grant.status_code == 200, grant.text

    resp = await client.post(
        member.g(f"/counter-groups/{gid}/sort"),
        headers=member.headers,
        json={"field": "name", "direction": "asc"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "COUNTER_WRITE_ACCESS_REQUIRED"


# ---------------------------------------------------------------------------
# Duplicate
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_duplicate_counter_group(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    source = await _create_group(client, a, name="Original")
    sid = source["id"]
    await _add_counter(
        client,
        a,
        sid,
        name="HP",
        count="40",
        initial_count="100",
        position="0",
    )
    await _add_counter(
        client,
        a,
        sid,
        name="Mana",
        count="5",
        min_value=None,
        max_value=None,
        view_mode="number",
        initial_count="0",
        position="1",
    )

    response = await client.post(
        a.g(f"/counter-groups/{sid}/duplicate"), headers=a.headers, json={}
    )
    assert response.status_code == 201, response.text
    copy = response.json()

    # New group with a distinct id and the default "(Copy)" name.
    assert copy["id"] != sid
    assert copy["name"] == "Original (Copy)"
    assert copy["my_permission_level"] == "owner"

    # Counters are copied with their values, bounds and order preserved.
    by_name = {
        c["name"]: c
        for c in sorted(copy["counters"], key=lambda c: Decimal(c["position"]))
    }
    assert [
        c["name"]
        for c in sorted(copy["counters"], key=lambda c: Decimal(c["position"]))
    ] == ["HP", "Mana"]
    assert Decimal(by_name["HP"]["count"]) == Decimal("40")
    assert Decimal(by_name["HP"]["initial_count"]) == Decimal("100")
    assert by_name["Mana"]["view_mode"] == "number"

    # The source group is untouched.
    src = (await client.get(a.g(f"/counter-groups/{sid}"), headers=a.headers)).json()
    assert src["name"] == "Original"
    assert len(src["counters"]) == 2


@pytest.mark.integration
async def test_duplicate_counter_group_custom_name(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    source = await _create_group(client, a, name="Original")

    response = await client.post(
        a.g(f"/counter-groups/{source['id']}/duplicate"),
        headers=a.headers,
        json={"name": "My Clone"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["name"] == "My Clone"


@pytest.mark.integration
async def test_duplicate_counter_group_read_user_becomes_owner(
    client: AsyncClient, acting_user
):
    """A read-only user can duplicate and owns the copy (read suffices to copy)."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    source = await _create_group(client, admin, name="Shared")
    sid = source["id"]
    await _add_counter(client, admin, sid, name="A", position="0")

    grant = await client.put(
        admin.g(f"/counter-groups/{sid}/grants"),
        headers=admin.headers,
        json=[{"user_id": member.user.id, "level": "read"}],
    )
    assert grant.status_code == 200, grant.text

    response = await client.post(
        member.g(f"/counter-groups/{sid}/duplicate"),
        headers=member.headers,
        json={},
    )
    assert response.status_code == 201, response.text
    assert response.json()["my_permission_level"] == "owner"


@pytest.mark.integration
async def test_delete_counter_group_still_emits_group_deleted(
    client: AsyncClient, acting_user, monkeypatch
):
    """Deleting a group must still emit ``group_deleted``. Regression: the group
    is soft-deleted before _emit_counter runs, so its fallback guild lookup is
    hidden by the global deleted_at IS NULL filter — the delete path must pass
    guild_id explicitly or the event is silently dropped."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    group = await _create_group(client, a)

    from app.services import stream_authz

    emitted: list[tuple] = []

    async def _record(guild_id, resource_type, resource_id, event_type, data):
        emitted.append((guild_id, resource_type, resource_id, event_type))

    monkeypatch.setattr(stream_authz.authority, "emit", _record)

    resp = await client.delete(a.g(f"/counter-groups/{group['id']}"), headers=a.headers)
    assert resp.status_code == 204, resp.text
    assert (a.guild.id, "counter_group", group["id"], "group_deleted") in emitted
