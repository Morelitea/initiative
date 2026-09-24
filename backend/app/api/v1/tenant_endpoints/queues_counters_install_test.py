"""Queues and counters as an installed app calls them.

Each test installs an app the way a community does (``install_app``: placed in
initiative A and not in B, granted scopes by the seat), seals an installation
token for it, and calls the queue and counter routes that name a scope: the
reads, create and update, the item edit, and the queue's and counters' own
commands.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlmodel import select

from app.core.messages import AppMessages
from app.core.tools import Tool
from app.models.tenant.counter import Counter, CounterGroup
from app.models.tenant.queue import Queue, QueueItem
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.services.marketplace import app_refs
from app.testing import (
    create_counter,
    create_counter_group,
    create_queue,
    create_queue_item,
    guild_of,
    route_session_to_guild,
)
from app.testing.app_clients import (
    assert_names_nobody,
    install_app,
    install_headers,
    lift_person_and_guild_ids,
)


pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _cold_reference_cache():
    app_refs.forget_cached_install_refs()
    yield
    app_refs.forget_cached_install_refs()


def _g(guild_id: int, path: str) -> str:
    return f"/api/v1/c/{guild_id}{path}"


async def _switch_on(session: Any, *initiatives: Any) -> None:
    """Turn queues and counters on in each of ``initiatives``."""
    await route_session_to_guild(session, guild_of(initiatives[0]))
    for initiative in initiatives:
        initiative.queues_enabled = True
        initiative.counter_groups_enabled = True
        session.add(initiative)
    await session.commit()


async def _share(
    session: Any,
    tool: Tool,
    resource_id: int,
    initiative_id: int,
    guild_id: int,
    level: ResourceAccessLevel = ResourceAccessLevel.read,
) -> None:
    """Share one resource with every member of its initiative, which an
    install placed there counts as."""
    await route_session_to_guild(session, guild_id)
    session.add(
        ResourceGrant(
            resource_type=tool.value,
            resource_id=resource_id,
            all_initiative_members=True,
            level=level,
            initiative_id=initiative_id,
        )
    )
    await session.commit()


async def _grants_of(
    session: Any, tool: Tool, resource_id: int, guild_id: int
) -> list[tuple[ResourceAccessLevel, int | None, int | None]]:
    await route_session_to_guild(session, guild_id)
    rows = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == tool.value,
                ResourceGrant.resource_id == resource_id,
            )
        )
    ).all()
    return [(g.level, g.app_install_id, g.user_id) for g in rows]


# ---------------------------------------------------------------------------
# Queues
# ---------------------------------------------------------------------------


async def test_reads_the_queues_open_to_its_initiative(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_app(
        session, acting_user, role_session, granted=["queues:read"]
    )
    seat = installed.seat
    guild_id = installed.guild.id
    await _switch_on(session, installed.placed, installed.unplaced)
    open_a = await create_queue(session, installed.placed, seat.user, name="Open A")
    await _share(session, Tool.queue, open_a.id, installed.placed.id, guild_id)
    item = await create_queue_item(
        session, open_a, label="Fighter", user_id=seat.user.id
    )
    await create_queue(session, installed.placed, seat.user, name="Private A")
    in_b = await create_queue(session, installed.unplaced, seat.user, name="Open B")
    await _share(session, Tool.queue, in_b.id, installed.unplaced.id, guild_id)
    item_b = await create_queue_item(session, in_b, label="Rogue")
    headers = install_headers(installed, ["queues:read"])

    listed = await client.get(_g(guild_id, "/queues/"), headers=headers)
    assert listed.status_code == 200, listed.text
    assert [q["name"] for q in listed.json()["items"]] == ["Open A"]
    assert_names_nobody(listed.text, [seat.user.id, guild_id])

    read = await client.get(_g(guild_id, f"/queues/{open_a.id}"), headers=headers)
    assert read.status_code == 200, read.text
    body = read.json()
    assert body["my_permission_level"] == "read"
    assert isinstance(body["guild_id"], str)
    assert isinstance(body["created_by"], str)
    [served] = body["items"]
    # The person the item names is the same reference as the queue's author.
    assert served["user_id"] == body["created_by"]
    assert served["user"]["id"] == body["created_by"]
    assert_names_nobody(read.text, [seat.user.id, guild_id])

    one = await client.get(_g(guild_id, f"/queue-items/{item.id}"), headers=headers)
    assert one.status_code == 200, one.text
    assert one.json()["user_id"] == body["created_by"]
    assert_names_nobody(one.text, [seat.user.id, guild_id])

    other = await client.get(_g(guild_id, f"/queues/{in_b.id}"), headers=headers)
    assert other.status_code == 404, other.text
    other_item = await client.get(
        _g(guild_id, f"/queue-items/{item_b.id}"), headers=headers
    )
    assert other_item.status_code == 404, other_item.text


async def test_a_queue_write_needs_the_write_scope(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["queues:write"]
    )
    guild_id = installed.guild.id
    await _switch_on(session, installed.placed)
    queue = await create_queue(session, installed.placed, installed.seat.user)
    await _share(
        session,
        Tool.queue,
        queue.id,
        installed.placed.id,
        guild_id,
        level=ResourceAccessLevel.write,
    )
    item = await create_queue_item(session, queue)
    headers = install_headers(installed, ["queues:read"])

    for method, path, payload in (
        ("post", "/queues/", {"name": "No", "initiative_id": installed.placed.id}),
        ("patch", f"/queues/{queue.id}", {"name": "No"}),
        ("patch", f"/queues/{queue.id}/items/{item.id}", {"label": "No"}),
        ("post", f"/queues/{queue.id}/next", None),
        ("post", f"/queues/{queue.id}/start", None),
    ):
        response = await client.request(
            method, _g(guild_id, path), headers=headers, json=payload
        )
        assert response.status_code == 403, (path, response.text)
        assert response.json()["detail"] == AppMessages.SCOPE_REQUIRED


async def test_what_it_creates_is_its_own_and_it_runs_the_turns(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_app(
        session, acting_user, role_session, granted=["queues:write"]
    )
    guild_id = installed.guild.id
    await _switch_on(session, installed.placed)
    headers = install_headers(installed, ["queues:write"])

    refused = await client.post(
        _g(guild_id, "/queues/"),
        headers=headers,
        json={
            "name": "Shared",
            "initiative_id": installed.placed.id,
            "grants": [{"all_initiative_members": True, "level": "write"}],
        },
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == AppMessages.SHARING_NOT_AVAILABLE

    created = await client.post(
        _g(guild_id, "/queues/"),
        headers=headers,
        json={"name": "Made by the app", "initiative_id": installed.placed.id},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["created_by"] is None
    assert body["my_permission_level"] == "owner"
    assert_names_nobody(created.text, [installed.seat.user.id, guild_id])
    assert await _grants_of(session, Tool.queue, body["id"], guild_id) == [
        (ResourceAccessLevel.owner, installed.app.id, None)
    ]
    queue = await session.get(Queue, body["id"])
    assert queue is not None and queue.created_by is None

    renamed = await client.patch(
        _g(guild_id, f"/queues/{body['id']}"),
        headers=headers,
        json={"name": "Renamed by the app"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Renamed by the app"

    first = await create_queue_item(session, queue, label="First", position=20)
    second = await create_queue_item(session, queue, label="Second", position=10)

    started = await client.post(
        _g(guild_id, f"/queues/{queue.id}/start"), headers=headers
    )
    assert started.status_code == 200, started.text
    assert started.json()["is_active"] is True
    assert started.json()["current_item"]["id"] == first.id

    advanced = await client.post(
        _g(guild_id, f"/queues/{queue.id}/next"), headers=headers
    )
    assert advanced.status_code == 200, advanced.text
    assert advanced.json()["current_item"]["id"] == second.id

    stopped = await client.post(
        _g(guild_id, f"/queues/{queue.id}/stop"), headers=headers
    )
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["is_active"] is False


async def test_it_runs_a_command_on_a_queue_shared_for_writing_only(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["queues:write"]
    )
    guild_id = installed.guild.id
    await _switch_on(session, installed.placed)
    writable = await create_queue(session, installed.placed, installed.seat.user)
    await _share(
        session,
        Tool.queue,
        writable.id,
        installed.placed.id,
        guild_id,
        level=ResourceAccessLevel.write,
    )
    readable = await create_queue(session, installed.placed, installed.seat.user)
    await _share(session, Tool.queue, readable.id, installed.placed.id, guild_id)
    for queue in (writable, readable):
        await create_queue_item(session, queue, label="Only")
    headers = install_headers(installed, ["queues:write"])

    ran = await client.post(
        _g(guild_id, f"/queues/{writable.id}/start"), headers=headers
    )
    assert ran.status_code == 200, ran.text
    assert ran.json()["my_permission_level"] == "write"

    refused = await client.post(
        _g(guild_id, f"/queues/{readable.id}/start"), headers=headers
    )
    assert refused.status_code == 403, refused.text


async def test_it_names_a_queue_items_person_by_reference(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_app(
        session, acting_user, role_session, granted=["queues:write"]
    )
    seat = installed.seat
    guild_id = installed.guild.id
    await _switch_on(session, installed.placed)
    queue = await create_queue(session, installed.placed, seat.user)
    await _share(
        session,
        Tool.queue,
        queue.id,
        installed.placed.id,
        guild_id,
        level=ResourceAccessLevel.write,
    )
    item = await create_queue_item(session, queue, label="Unclaimed")
    headers = install_headers(installed, ["queues:write"])

    read = await client.get(_g(guild_id, f"/queues/{queue.id}"), headers=headers)
    assert read.status_code == 200, read.text
    reference = read.json()["created_by"]
    assert isinstance(reference, str)

    claimed = await client.patch(
        _g(guild_id, f"/queues/{queue.id}/items/{item.id}"),
        headers=headers,
        json={"user_id": reference},
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["user_id"] == reference
    assert_names_nobody(claimed.text, [seat.user.id, guild_id])
    await route_session_to_guild(session, guild_id)
    stored = await session.get(QueueItem, item.id, populate_existing=True)
    assert stored is not None and stored.user_id == seat.user.id

    by_row_id = await client.patch(
        _g(guild_id, f"/queues/{queue.id}/items/{item.id}"),
        headers=headers,
        json={"user_id": seat.user.id},
    )
    assert by_row_id.status_code == 422, by_row_id.text


# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------


async def test_reads_the_counter_groups_open_to_its_initiative(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_app(
        session, acting_user, role_session, granted=["counter_groups:read"]
    )
    seat = installed.seat
    guild_id = installed.guild.id
    await _switch_on(session, installed.placed, installed.unplaced)
    open_a = await create_counter_group(
        session, installed.placed, seat.user, name="Open A"
    )
    await _share(session, Tool.counter_group, open_a.id, installed.placed.id, guild_id)
    counter = await create_counter(session, open_a, name="Hit points")
    await create_counter_group(session, installed.placed, seat.user, name="Private A")
    in_b = await create_counter_group(
        session, installed.unplaced, seat.user, name="Open B"
    )
    await _share(session, Tool.counter_group, in_b.id, installed.unplaced.id, guild_id)
    counter_b = await create_counter(session, in_b, name="Gold")
    headers = install_headers(installed, ["counter_groups:read"])

    listed = await client.get(_g(guild_id, "/counter-groups/"), headers=headers)
    assert listed.status_code == 200, listed.text
    assert [g["name"] for g in listed.json()["items"]] == ["Open A"]
    assert_names_nobody(listed.text, [seat.user.id, guild_id])

    read = await client.get(
        _g(guild_id, f"/counter-groups/{open_a.id}"), headers=headers
    )
    assert read.status_code == 200, read.text
    body = read.json()
    assert body["my_permission_level"] == "read"
    assert isinstance(body["created_by"], str)
    assert [c["name"] for c in body["counters"]] == ["Hit points"]
    assert isinstance(body["counters"][0]["guild_id"], str)
    assert_names_nobody(read.text, [seat.user.id, guild_id])

    one = await client.get(_g(guild_id, f"/counters/{counter.id}"), headers=headers)
    assert one.status_code == 200, one.text
    assert one.json()["guild_id"] == body["guild_id"]
    assert_names_nobody(one.text, [seat.user.id, guild_id])

    other = await client.get(
        _g(guild_id, f"/counter-groups/{in_b.id}"), headers=headers
    )
    assert other.status_code == 404, other.text
    other_counter = await client.get(
        _g(guild_id, f"/counters/{counter_b.id}"), headers=headers
    )
    assert other_counter.status_code == 404, other_counter.text


async def test_a_counter_write_needs_the_write_scope(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["counter_groups:write"]
    )
    guild_id = installed.guild.id
    await _switch_on(session, installed.placed)
    group = await create_counter_group(session, installed.placed, installed.seat.user)
    await _share(
        session,
        Tool.counter_group,
        group.id,
        installed.placed.id,
        guild_id,
        level=ResourceAccessLevel.write,
    )
    counter = await create_counter(session, group)
    headers = install_headers(installed, ["counter_groups:read"])

    base = f"/counter-groups/{group.id}/counters/{counter.id}"
    for method, path, payload in (
        (
            "post",
            "/counter-groups/",
            {"name": "No", "initiative_id": installed.placed.id},
        ),
        ("patch", f"/counter-groups/{group.id}", {"name": "No"}),
        ("post", f"{base}/increment", None),
        ("post", f"{base}/set", {"count": "3"}),
    ):
        response = await client.request(
            method, _g(guild_id, path), headers=headers, json=payload
        )
        assert response.status_code == 403, (path, response.text)
        assert response.json()["detail"] == AppMessages.SCOPE_REQUIRED


async def test_what_it_creates_is_its_own_and_it_steps_the_counters(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_app(
        session, acting_user, role_session, granted=["counter_groups:write"]
    )
    guild_id = installed.guild.id
    await _switch_on(session, installed.placed)
    headers = install_headers(installed, ["counter_groups:write"])

    refused = await client.post(
        _g(guild_id, "/counter-groups/"),
        headers=headers,
        json={
            "name": "Shared",
            "initiative_id": installed.placed.id,
            "grants": [{"all_initiative_members": True, "level": "read"}],
        },
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == AppMessages.SHARING_NOT_AVAILABLE

    created = await client.post(
        _g(guild_id, "/counter-groups/"),
        headers=headers,
        json={"name": "Made by the app", "initiative_id": installed.placed.id},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["created_by"] is None
    assert body["my_permission_level"] == "owner"
    assert_names_nobody(created.text, [installed.seat.user.id, guild_id])
    assert await _grants_of(session, Tool.counter_group, body["id"], guild_id) == [
        (ResourceAccessLevel.owner, installed.app.id, None)
    ]
    group = await session.get(CounterGroup, body["id"])
    assert group is not None and group.created_by is None

    renamed = await client.patch(
        _g(guild_id, f"/counter-groups/{group.id}"),
        headers=headers,
        json={"description": "Kept by the app"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["description"] == "Kept by the app"

    counter = await create_counter(session, group, name="Round", initial_count=1)
    base = _g(guild_id, f"/counter-groups/{group.id}/counters/{counter.id}")

    stepped = await client.post(f"{base}/increment", headers=headers)
    assert stepped.status_code == 200, stepped.text
    assert stepped.json()["count"] == "1"
    down = await client.post(f"{base}/decrement", headers=headers)
    assert down.status_code == 200, down.text
    assert down.json()["count"] == "0"
    set_to = await client.post(f"{base}/set", headers=headers, json={"count": "7"})
    assert set_to.status_code == 200, set_to.text
    assert set_to.json()["count"] == "7"
    reset = await client.post(f"{base}/reset", headers=headers)
    assert reset.status_code == 200, reset.text
    assert reset.json()["count"] == "1"
    assert_names_nobody(reset.text, [installed.seat.user.id, guild_id])

    await route_session_to_guild(session, guild_id)
    stored = await session.get(Counter, counter.id, populate_existing=True)
    assert stored is not None and stored.count == Decimal("1")


async def test_it_steps_a_counter_shared_for_writing_only(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["counter_groups:write"]
    )
    guild_id = installed.guild.id
    await _switch_on(session, installed.placed)
    writable = await create_counter_group(
        session, installed.placed, installed.seat.user
    )
    await _share(
        session,
        Tool.counter_group,
        writable.id,
        installed.placed.id,
        guild_id,
        level=ResourceAccessLevel.write,
    )
    readable = await create_counter_group(
        session, installed.placed, installed.seat.user
    )
    await _share(
        session, Tool.counter_group, readable.id, installed.placed.id, guild_id
    )
    on_writable = await create_counter(session, writable)
    on_readable = await create_counter(session, readable)
    headers = install_headers(installed, ["counter_groups:write"])

    ran = await client.post(
        _g(
            guild_id,
            f"/counter-groups/{writable.id}/counters/{on_writable.id}/increment",
        ),
        headers=headers,
    )
    assert ran.status_code == 200, ran.text
    assert ran.json()["count"] == "1"

    refused = await client.post(
        _g(
            guild_id,
            f"/counter-groups/{readable.id}/counters/{on_readable.id}/increment",
        ),
        headers=headers,
    )
    assert refused.status_code == 403, refused.text
