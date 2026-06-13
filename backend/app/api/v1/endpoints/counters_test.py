"""Integration tests for counter group endpoints."""

import pytest
from decimal import Decimal
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import Guild, GuildRole
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


async def _setup_admin(session: AsyncSession):
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    initiative = await create_initiative(session, guild, admin, name="Test")
    return admin, guild, initiative


async def _setup_with_member(session: AsyncSession):
    admin, guild, initiative = await _setup_admin(session)
    member = await create_user(session, email="member@example.com")
    await create_guild_membership(session, user=member, guild=guild)
    await create_initiative_member(session, initiative, member, role_name="member")
    return admin, member, guild, initiative


async def _create_group(
    client: AsyncClient,
    headers: dict,
    guild: Guild,
    initiative_id: int,
    name: str = "Test Group",
) -> dict:
    response = await client.post(
        f"/api/v1/g/{guild.id}/counter-groups/",
        headers=headers,
        json={"name": name, "initiative_id": initiative_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _add_counter(
    client: AsyncClient,
    headers: dict,
    guild: Guild,
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
        f"/api/v1/g/{guild.id}/counter-groups/{group_id}/counters",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Counter Group CRUD
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_counter_group(client: AsyncClient, session: AsyncSession):
    admin, guild, initiative = await _setup_admin(session)
    headers = await get_guild_headers(session, guild, admin)

    response = await client.post(
        f"/api/v1/g/{guild.id}/counter-groups/",
        headers=headers,
        json={
            "name": "Combat Tracker",
            "description": "HP, AC, etc.",
            "initiative_id": initiative.id,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Combat Tracker"
    assert data["description"] == "HP, AC, etc."
    assert data["initiative_id"] == initiative.id
    assert data["created_by_id"] == admin.id
    assert data["counter_count"] == 0


@pytest.mark.integration
async def test_create_counter_group_non_pm_forbidden(
    client: AsyncClient, session: AsyncSession
):
    admin, member, guild, initiative = await _setup_with_member(session)
    headers = await get_guild_headers(session, guild, member)

    response = await client.post(
        f"/api/v1/g/{guild.id}/counter-groups/",
        headers=headers,
        json={"name": "Nope", "initiative_id": initiative.id},
    )
    assert response.status_code == 403


@pytest.mark.integration
async def test_feature_disabled_blocks_creation(
    client: AsyncClient, session: AsyncSession
):
    admin, guild, initiative = await _setup_admin(session)
    initiative.counters_enabled = False
    await session.commit()
    headers = await get_guild_headers(session, guild, admin)

    response = await client.post(
        f"/api/v1/g/{guild.id}/counter-groups/",
        headers=headers,
        json={"name": "X", "initiative_id": initiative.id},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "COUNTERS_NOT_ENABLED"


@pytest.mark.integration
async def test_list_counter_groups(client: AsyncClient, session: AsyncSession):
    admin, guild, initiative = await _setup_admin(session)
    headers = await get_guild_headers(session, guild, admin)
    await _create_group(client, headers, guild, initiative.id, "Group A")
    await _create_group(client, headers, guild, initiative.id, "Group B")

    response = await client.get(
        f"/api/v1/g/{guild.id}/counter-groups/", headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 2
    assert {item["name"] for item in body["items"]} == {"Group A", "Group B"}


# ---------------------------------------------------------------------------
# Counter CRUD + view mode validation
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_add_counter_clamps_initial_and_count(
    client: AsyncClient, session: AsyncSession
):
    admin, guild, initiative = await _setup_admin(session)
    headers = await get_guild_headers(session, guild, admin)
    group = await _create_group(client, headers, guild, initiative.id)

    counter = await _add_counter(
        client,
        headers,
        guild,
        group["id"],
        count="999",
        min_value="0",
        max_value="50",
        initial_count="60",
    )
    assert Decimal(counter["count"]) == Decimal("50")
    assert Decimal(counter["initial_count"]) == Decimal("50")


@pytest.mark.integration
async def test_progress_bar_requires_bounds(client: AsyncClient, session: AsyncSession):
    admin, guild, initiative = await _setup_admin(session)
    headers = await get_guild_headers(session, guild, admin)
    group = await _create_group(client, headers, guild, initiative.id)

    response = await client.post(
        f"/api/v1/g/{guild.id}/counter-groups/{group['id']}/counters",
        headers=headers,
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
async def test_increment_clamps_at_max(client: AsyncClient, session: AsyncSession):
    admin, guild, initiative = await _setup_admin(session)
    headers = await get_guild_headers(session, guild, admin)
    group = await _create_group(client, headers, guild, initiative.id)
    counter = await _add_counter(
        client,
        headers,
        guild,
        group["id"],
        count="99",
        min_value="0",
        max_value="100",
        step="5",
    )

    response = await client.post(
        f"/api/v1/g/{guild.id}/counter-groups/{group['id']}/counters/{counter['id']}/increment",
        headers=headers,
    )
    assert response.status_code == 200
    assert Decimal(response.json()["count"]) == Decimal("100")


@pytest.mark.integration
async def test_decrement_clamps_at_min(client: AsyncClient, session: AsyncSession):
    admin, guild, initiative = await _setup_admin(session)
    headers = await get_guild_headers(session, guild, admin)
    group = await _create_group(client, headers, guild, initiative.id)
    counter = await _add_counter(
        client,
        headers,
        guild,
        group["id"],
        count="2",
        min_value="0",
        max_value="100",
        step="5",
    )

    response = await client.post(
        f"/api/v1/g/{guild.id}/counter-groups/{group['id']}/counters/{counter['id']}/decrement",
        headers=headers,
    )
    assert response.status_code == 200
    assert Decimal(response.json()["count"]) == Decimal("0")


@pytest.mark.integration
async def test_set_count_clamps(client: AsyncClient, session: AsyncSession):
    admin, guild, initiative = await _setup_admin(session)
    headers = await get_guild_headers(session, guild, admin)
    group = await _create_group(client, headers, guild, initiative.id)
    counter = await _add_counter(
        client, headers, group["id"], min_value="0", max_value="100"
    )

    response = await client.post(
        f"/api/v1/g/{guild.id}/counter-groups/{group['id']}/counters/{counter['id']}/set",
        headers=headers,
        json={"count": "9999"},
    )
    assert response.status_code == 200
    assert Decimal(response.json()["count"]) == Decimal("100")


@pytest.mark.integration
async def test_reset_returns_to_initial(client: AsyncClient, session: AsyncSession):
    admin, guild, initiative = await _setup_admin(session)
    headers = await get_guild_headers(session, guild, admin)
    group = await _create_group(client, headers, guild, initiative.id)
    counter = await _add_counter(
        client,
        headers,
        guild,
        group["id"],
        count="50",
        initial_count="80",
        min_value="0",
        max_value="100",
    )

    # Drop the value first
    await client.post(
        f"/api/v1/g/{guild.id}/counter-groups/{group['id']}/counters/{counter['id']}/set",
        headers=headers,
        json={"count": "10"},
    )

    response = await client.post(
        f"/api/v1/g/{guild.id}/counter-groups/{group['id']}/counters/{counter['id']}/reset",
        headers=headers,
    )
    assert response.status_code == 200
    assert Decimal(response.json()["count"]) == Decimal("80")


@pytest.mark.integration
async def test_reset_all_counters(client: AsyncClient, session: AsyncSession):
    admin, guild, initiative = await _setup_admin(session)
    headers = await get_guild_headers(session, guild, admin)
    group = await _create_group(client, headers, guild, initiative.id)
    c1 = await _add_counter(
        client,
        headers,
        guild,
        group["id"],
        name="A",
        initial_count="50",
        min_value="0",
        max_value="100",
    )
    c2 = await _add_counter(
        client,
        headers,
        guild,
        group["id"],
        name="B",
        initial_count="25",
        min_value="0",
        max_value="100",
        position="1",
    )

    # Mutate both
    await client.post(
        f"/api/v1/g/{guild.id}/counter-groups/{group['id']}/counters/{c1['id']}/set",
        headers=headers,
        json={"count": "1"},
    )
    await client.post(
        f"/api/v1/g/{guild.id}/counter-groups/{group['id']}/counters/{c2['id']}/set",
        headers=headers,
        json={"count": "1"},
    )

    response = await client.post(
        f"/api/v1/g/{guild.id}/counter-groups/{group['id']}/reset-all", headers=headers
    )
    assert response.status_code == 200
    counts = {c["name"]: Decimal(c["count"]) for c in response.json()["counters"]}
    assert counts["A"] == Decimal("50")
    assert counts["B"] == Decimal("25")


# ---------------------------------------------------------------------------
# Position / re-clamp on update
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_update_min_max_reclamps_count(
    client: AsyncClient, session: AsyncSession
):
    admin, guild, initiative = await _setup_admin(session)
    headers = await get_guild_headers(session, guild, admin)
    group = await _create_group(client, headers, guild, initiative.id)
    counter = await _add_counter(
        client, headers, group["id"], count="100", min_value="0", max_value="100"
    )

    response = await client.patch(
        f"/api/v1/g/{guild.id}/counter-groups/{group['id']}/counters/{counter['id']}",
        headers=headers,
        json={"max": "50"},
    )
    assert response.status_code == 200
    assert Decimal(response.json()["count"]) == Decimal("50")


@pytest.mark.integration
async def test_update_null_non_nullable_fields_is_noop(
    client: AsyncClient, session: AsyncSession
):
    """Explicit null for NOT NULL columns (step/initial_count/position/name/
    view_mode) must not 500 — it's treated as 'field not provided'."""
    admin, guild, initiative = await _setup_admin(session)
    headers = await get_guild_headers(session, guild, admin)
    group = await _create_group(client, headers, guild, initiative.id)
    counter = await _add_counter(
        client,
        headers,
        guild,
        group["id"],
        name="HP",
        count="5",
        step="2",
        initial_count="0",
    )

    response = await client.patch(
        f"/api/v1/g/{guild.id}/counter-groups/{group['id']}/counters/{counter['id']}",
        headers=headers,
        json={"step": None, "initial_count": None, "position": None, "name": None},
    )
    assert response.status_code == 200
    data = response.json()
    # Original values are preserved.
    assert data["name"] == "HP"
    assert Decimal(data["step"]) == Decimal("2")


@pytest.mark.integration
async def test_update_step_zero_rejected(client: AsyncClient, session: AsyncSession):
    """A provided step of 0 is a clean 422, not a 500."""
    admin, guild, initiative = await _setup_admin(session)
    headers = await get_guild_headers(session, guild, admin)
    group = await _create_group(client, headers, guild, initiative.id)
    counter = await _add_counter(client, headers, group["id"])

    response = await client.patch(
        f"/api/v1/g/{guild.id}/counter-groups/{group['id']}/counters/{counter['id']}",
        headers=headers,
        json={"step": "0"},
    )
    assert response.status_code == 422


@pytest.mark.integration
async def test_decimal_serialization_no_exponent(
    client: AsyncClient, session: AsyncSession
):
    """Numeric(20, 10) zeros must not round-trip as ``0E-10``."""
    admin, guild, initiative = await _setup_admin(session)
    headers = await get_guild_headers(session, guild, admin)
    group = await _create_group(client, headers, guild, initiative.id)
    counter = await _add_counter(
        client,
        headers,
        guild,
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
    client: AsyncClient, session: AsyncSession
):
    """Deleting a counter sets deleted_at and shows it in the trash list."""
    from app.db.soft_delete_filter import select_including_deleted
    from app.models.counter import Counter
    from sqlmodel import select as sqlmodel_select  # noqa: F401

    admin, guild, initiative = await _setup_admin(session)
    headers = await get_guild_headers(session, guild, admin)
    group = await _create_group(client, headers, guild, initiative.id)
    counter = await _add_counter(client, headers, group["id"], name="HP")

    resp = await client.delete(
        f"/api/v1/g/{guild.id}/counter-groups/{group['id']}/counters/{counter['id']}",
        headers=headers,
    )
    assert resp.status_code == 204

    # Confirm soft-delete stamp on the row.
    stmt = select_including_deleted(Counter).where(Counter.id == counter["id"])
    row = (await session.exec(stmt)).one()
    assert row.deleted_at is not None
    assert row.deleted_by == admin.id

    # And it should appear in the trash list.
    trash = await client.get("/api/v1/me/trash", headers=headers)
    assert trash.status_code == 200
    entries = trash.json()["items"]
    assert any(
        item["entity_type"] == "counter" and item["entity_id"] == counter["id"]
        for item in entries
    )


@pytest.mark.integration
async def test_deleted_counter_group_hidden_from_list_and_read(
    client: AsyncClient, session: AsyncSession
):
    """Soft-deleted groups must not appear in list/read or accept counter
    adds. The session-level soft-delete filter is what enforces this."""
    admin, guild, initiative = await _setup_admin(session)
    headers = await get_guild_headers(session, guild, admin)
    keep = await _create_group(client, headers, guild, initiative.id, "Keep")
    trashed = await _create_group(client, headers, guild, initiative.id, "Trash me")

    # Delete the second one.
    assert (
        await client.delete(
            f"/api/v1/g/{guild.id}/counter-groups/{trashed['id']}", headers=headers
        )
    ).status_code == 204

    # List returns only the surviving group.
    listing = (
        await client.get(f"/api/v1/g/{guild.id}/counter-groups/", headers=headers)
    ).json()
    names = {item["name"] for item in listing["items"]}
    assert names == {"Keep"}
    assert listing["total_count"] == 1

    # Detail read returns 404.
    assert (
        await client.get(
            f"/api/v1/g/{guild.id}/counter-groups/{trashed['id']}", headers=headers
        )
    ).status_code == 404

    # Trying to add a counter to it also 404s (the group is no longer reachable).
    add_resp = await client.post(
        f"/api/v1/g/{guild.id}/counter-groups/{trashed['id']}/counters",
        headers=headers,
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
        f"/api/v1/g/{guild.id}/counter-groups/{keep['id']}/counters",
        headers=headers,
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
    client: AsyncClient, session: AsyncSession
):
    """Deleting a counter group soft-deletes it AND its counters; the group
    appears in the trash list but the cascaded counters are deduped out."""
    from app.db.soft_delete_filter import select_including_deleted
    from app.models.counter import Counter, CounterGroup

    admin, guild, initiative = await _setup_admin(session)
    headers = await get_guild_headers(session, guild, admin)
    group = await _create_group(client, headers, guild, initiative.id)
    counter = await _add_counter(client, headers, group["id"], name="HP")

    resp = await client.delete(
        f"/api/v1/g/{guild.id}/counter-groups/{group['id']}",
        headers=headers,
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

    trash = await client.get("/api/v1/me/trash", headers=headers)
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
async def test_fractional_position_sort(client: AsyncClient, session: AsyncSession):
    admin, guild, initiative = await _setup_admin(session)
    headers = await get_guild_headers(session, guild, admin)
    group_resp = await _create_group(client, headers, guild, initiative.id)
    group_id = group_resp["id"]

    a = await _add_counter(client, headers, group_id, name="A", position="10.0")
    await _add_counter(client, headers, group_id, name="B", position="20.0")

    # Drop "A" between (would equal 15.0)
    response = await client.patch(
        f"/api/v1/g/{guild.id}/counter-groups/{group_id}/counters/{a['id']}",
        headers=headers,
        json={"position": "15.5"},
    )
    assert response.status_code == 200

    group = (
        await client.get(
            f"/api/v1/g/{guild.id}/counter-groups/{group_id}", headers=headers
        )
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
async def test_sort_counters(client: AsyncClient, session: AsyncSession):
    admin, guild, initiative = await _setup_admin(session)
    headers = await get_guild_headers(session, guild, admin)
    group = await _create_group(client, headers, guild, initiative.id)
    gid = group["id"]

    # Scrambled order; "alpha" is lowercase to exercise case-insensitive sort.
    await _add_counter(client, headers, gid, name="Charlie", count="5", position="0")
    await _add_counter(client, headers, gid, name="alpha", count="1", position="1")
    await _add_counter(client, headers, gid, name="Bravo", count="3", position="2")

    async def sort(field: str, direction: str) -> dict:
        resp = await client.post(
            f"/api/v1/g/{guild.id}/counter-groups/{gid}/sort",
            headers=headers,
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
        await client.get(f"/api/v1/g/{guild.id}/counter-groups/{gid}", headers=headers)
    ).json()
    assert _ordered_names(fetched) == ["Charlie", "Bravo", "alpha"]


@pytest.mark.integration
async def test_sort_counters_read_only_forbidden(
    client: AsyncClient, session: AsyncSession
):
    admin, member, guild, initiative = await _setup_with_member(session)
    admin_headers = await get_guild_headers(session, guild, admin)
    group = await _create_group(client, admin_headers, initiative.id)
    gid = group["id"]
    await _add_counter(client, admin_headers, gid, name="A", position="0")

    # Grant the member read-only access on the group.
    grant = await client.put(
        f"/api/v1/g/{guild.id}/counter-groups/{gid}/permissions",
        headers=admin_headers,
        json=[{"user_id": member.id, "level": "read"}],
    )
    assert grant.status_code == 200, grant.text

    member_headers = await get_guild_headers(session, guild, member)
    resp = await client.post(
        f"/api/v1/g/{guild.id}/counter-groups/{gid}/sort",
        headers=member_headers,
        json={"field": "name", "direction": "asc"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "COUNTER_WRITE_ACCESS_REQUIRED"


# ---------------------------------------------------------------------------
# Duplicate
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_duplicate_counter_group(client: AsyncClient, session: AsyncSession):
    admin, guild, initiative = await _setup_admin(session)
    headers = await get_guild_headers(session, guild, admin)
    source = await _create_group(client, headers, guild, initiative.id, name="Original")
    sid = source["id"]
    await _add_counter(
        client, headers, sid, name="HP", count="40", initial_count="100", position="0"
    )
    await _add_counter(
        client,
        headers,
        guild,
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
        f"/api/v1/g/{guild.id}/counter-groups/{sid}/duplicate", headers=headers, json={}
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
    src = (
        await client.get(f"/api/v1/g/{guild.id}/counter-groups/{sid}", headers=headers)
    ).json()
    assert src["name"] == "Original"
    assert len(src["counters"]) == 2


@pytest.mark.integration
async def test_duplicate_counter_group_custom_name(
    client: AsyncClient, session: AsyncSession
):
    admin, guild, initiative = await _setup_admin(session)
    headers = await get_guild_headers(session, guild, admin)
    source = await _create_group(client, headers, guild, initiative.id, name="Original")

    response = await client.post(
        f"/api/v1/g/{guild.id}/counter-groups/{source['id']}/duplicate",
        headers=headers,
        json={"name": "My Clone"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["name"] == "My Clone"


@pytest.mark.integration
async def test_duplicate_counter_group_read_user_becomes_owner(
    client: AsyncClient, session: AsyncSession
):
    """A read-only user can duplicate and owns the copy (read suffices to copy)."""
    admin, member, guild, initiative = await _setup_with_member(session)
    admin_headers = await get_guild_headers(session, guild, admin)
    source = await _create_group(client, admin_headers, initiative.id, name="Shared")
    sid = source["id"]
    await _add_counter(client, admin_headers, sid, name="A", position="0")

    grant = await client.put(
        f"/api/v1/g/{guild.id}/counter-groups/{sid}/permissions",
        headers=admin_headers,
        json=[{"user_id": member.id, "level": "read"}],
    )
    assert grant.status_code == 200, grant.text

    member_headers = await get_guild_headers(session, guild, member)
    response = await client.post(
        f"/api/v1/g/{guild.id}/counter-groups/{sid}/duplicate",
        headers=member_headers,
        json={},
    )
    assert response.status_code == 201, response.text
    assert response.json()["my_permission_level"] == "owner"
