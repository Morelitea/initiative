"""The task and task-status routes an installed app calls.

Each test installs an app (placed in initiative A, not in B) and calls the
routes with its installation token on the real-role client. A task answers to
the projects scopes; people in requests and responses are named by the
install's own references.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlmodel import select

from app.core.messages import AppMessages, QueryMessages
from app.models.platform.notification import Notification, NotificationType
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.models.tenant.task import Task
from app.services.marketplace import app_refs
from app.models.tenant.property import PropertyType
from app.testing import (
    create_project,
    create_property_definition,
    create_task,
    route_session_to_guild,
)
from app.testing.app_clients import (
    assert_names_nobody,
    install_app,
    install_headers,
    lift_person_and_guild_ids,
)

pytestmark = pytest.mark.integration

READ = ["projects:read"]
WRITE = ["projects:read", "projects:write"]


@pytest.fixture(autouse=True)
def _cold_reference_cache():
    app_refs.forget_cached_install_refs()
    yield
    app_refs.forget_cached_install_refs()


def _g(guild_id: int, path: str) -> str:
    return f"/api/v1/g/{guild_id}{path}"


def _at(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=timezone.utc)


async def _share(session: Any, guild_id: int, project: Any) -> None:
    await route_session_to_guild(session, guild_id)
    session.add(
        ResourceGrant(
            resource_type="project",
            resource_id=project.id,
            all_initiative_members=True,
            level=ResourceAccessLevel.read,
            initiative_id=project.initiative_id,
        )
    )
    await session.commit()


async def _reference_for_seat(
    client: Any, session: Any, installed: Any, headers: dict
) -> str:
    """What the install calls the seat, from the owner of a project the seat
    made and shared with the install's initiative."""
    project = await create_project(
        session, installed.placed, installed.seat.user, name="Seat's"
    )
    await _share(session, installed.guild.id, project)
    read = await client.get(
        _g(installed.guild.id, f"/projects/{project.id}"), headers=headers
    )
    assert read.status_code == 200, read.text
    reference = read.json()["owner_id"]
    assert isinstance(reference, str)
    return reference


async def _own_project(client: Any, installed: Any, headers: dict, name: str) -> int:
    created = await client.post(
        _g(installed.guild.id, "/projects/"),
        headers=headers,
        json={"name": name, "initiative_id": installed.placed.id},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def _assignment_lines(session: Any, user_id: int) -> list[Notification]:
    return list(
        (
            await session.exec(
                select(Notification).where(
                    Notification.user_id == user_id,
                    Notification.type == NotificationType.task_assignment,
                )
            )
        ).all()
    )


# ---------------------------------------------------------------------------
# Reach
# ---------------------------------------------------------------------------


async def test_reads_the_tasks_of_projects_open_to_its_initiative(
    client, session, acting_user, role_session
):
    installed = await install_app(session, acting_user, role_session, granted=READ)
    in_a = await create_project(
        session, installed.placed, installed.seat.user, name="Open in A"
    )
    await _share(session, installed.guild.id, in_a)
    in_b = await create_project(
        session, installed.unplaced, installed.seat.user, name="Open in B"
    )
    await _share(session, installed.guild.id, in_b)
    task_a = await create_task(session, in_a, title="Task in A")
    task_b = await create_task(session, in_b, title="Task in B")
    headers = install_headers(installed, READ)
    gid = installed.guild.id

    listed = await client.get(_g(gid, "/tasks/"), headers=headers)
    assert listed.status_code == 200, listed.text
    assert [t["title"] for t in listed.json()["items"]] == ["Task in A"]

    read = await client.get(_g(gid, f"/tasks/{task_a.id}"), headers=headers)
    assert read.status_code == 200, read.text
    assert read.json()["title"] == "Task in A"
    other = await client.get(_g(gid, f"/tasks/{task_b.id}"), headers=headers)
    assert other.status_code == 404, other.text

    statuses = await client.get(
        _g(gid, f"/projects/{in_a.id}/task-statuses/"), headers=headers
    )
    assert statuses.status_code == 200, statuses.text
    assert [s["id"] for s in statuses.json()] == [task_a.task_status_id]
    hidden = await client.get(
        _g(gid, f"/projects/{in_b.id}/task-statuses/"), headers=headers
    )
    assert hidden.status_code == 404, hidden.text

    gathered = await client.get(
        _g(gid, f"/initiatives/{installed.placed.id}/task-statuses/"),
        headers=headers,
    )
    assert gathered.status_code == 200, gathered.text
    assert [(s["name"], s["project_count"]) for s in gathered.json()] == [("Todo", 1)]
    unplaced = await client.get(
        _g(gid, f"/initiatives/{installed.unplaced.id}/task-statuses/"),
        headers=headers,
    )
    assert unplaced.status_code == 404, unplaced.text


async def test_lists_with_the_filters_a_scan_sends(
    client, session, acting_user, role_session
):
    installed = await install_app(session, acting_user, role_session, granted=READ)
    project = await create_project(session, installed.placed, installed.seat.user)
    await _share(session, installed.guild.id, project)
    await create_task(session, project, title="Late", due_date=_at("2026-01-02"))
    await create_task(session, project, title="Later", due_date=_at("2026-03-02"))
    headers = install_headers(installed, READ)
    conditions = [
        {"field": "due_date", "op": "gte", "value": "2026-01-01T00:00:00+00:00"},
        {"field": "due_date", "op": "lt", "value": "2026-02-01T00:00:00+00:00"},
        {
            "field": "status_category",
            "op": "in_",
            "value": ["done"],
            "negate": True,
        },
        {"field": "initiative_ids", "op": "in_", "value": [installed.placed.id]},
    ]

    listed = await client.get(
        _g(installed.guild.id, "/tasks/"),
        headers=headers,
        params={
            "conditions": json.dumps(conditions),
            "sorting": json.dumps([{"field": "due_date", "dir": "asc"}]),
            "page": 1,
            "page_size": 100,
        },
    )
    assert listed.status_code == 200, listed.text
    assert [t["title"] for t in listed.json()["items"]] == ["Late"]

    # A filter whose values are people's row ids is a person's to send.
    by_person = await client.get(
        _g(installed.guild.id, "/tasks/"),
        headers=headers,
        params={
            "conditions": json.dumps(
                [{"field": "assignee_ids", "op": "in_", "value": ["me"]}]
            )
        },
    )
    assert by_person.status_code == 400, by_person.text
    assert by_person.json()["detail"] == QueryMessages.INVALID_CONDITIONS


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


async def test_a_write_needs_the_write_scope(
    client, session, acting_user, role_session
):
    installed = await install_app(session, acting_user, role_session, granted=WRITE)
    project = await create_project(session, installed.placed, installed.seat.user)
    await _share(session, installed.guild.id, project)
    task = await create_task(session, project, title="Read only")
    other = await create_project(session, installed.placed, installed.seat.user)
    headers = install_headers(installed, READ)
    gid = installed.guild.id

    attempts = [
        client.post(
            _g(gid, "/tasks/"),
            headers=headers,
            json={"project_id": project.id, "title": "No"},
        ),
        client.patch(
            _g(gid, f"/tasks/{task.id}"), headers=headers, json={"title": "No"}
        ),
        client.post(
            _g(gid, f"/tasks/{task.id}/move"),
            headers=headers,
            json={"target_project_id": other.id},
        ),
        client.patch(
            _g(gid, f"/tasks/{task.id}/checklist/item1"),
            headers=headers,
            json={"done": True},
        ),
    ]
    for attempt in attempts:
        response = await attempt
        assert response.status_code == 403, response.text
        assert response.json()["detail"] == AppMessages.SCOPE_REQUIRED


async def test_creates_a_task_assigned_by_reference_and_names_nobody(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_app(session, acting_user, role_session, granted=WRITE)
    headers = install_headers(installed, WRITE)
    gid = installed.guild.id
    seat_ref = await _reference_for_seat(client, session, installed, headers)
    project_id = await _own_project(client, installed, headers, "The app's")

    created = await client.post(
        _g(gid, "/tasks/"),
        headers=headers,
        json={
            "project_id": project_id,
            "title": "Made by the app",
            "description": "Follow up",
            "priority": "high",
            "due_date": "2026-10-01T09:00:00+00:00",
            "assignee_ids": [seat_ref],
            "checklist": [{"text": "First"}],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["created_by"] is None
    assert [a["id"] for a in body["assignees"]] == [seat_ref]
    assert_names_nobody(created.text, [installed.seat.user.id, gid])

    listed = await client.get(_g(gid, "/tasks/"), headers=headers)
    assert listed.status_code == 200, listed.text
    row = next(t for t in listed.json()["items"] if t["id"] == body["id"])
    assert [a["id"] for a in row["assignees"]] == [seat_ref]
    assert isinstance(row["guild_id"], str)
    assert_names_nobody(listed.text, [installed.seat.user.id, gid])

    await route_session_to_guild(session, gid)
    stored = await session.get(Task, body["id"])
    assert stored is not None and stored.created_by is None

    lines = await _assignment_lines(session, installed.seat.user.id)
    assert [line.data["assigned_by_name"] for line in lines] == [installed.app.name]

    # A person reading the same task is served row ids, as always.
    person = await client.get(
        _g(gid, f"/tasks/{body['id']}"), headers=installed.seat.headers
    )
    assert person.status_code == 200, person.text
    assert [a["id"] for a in person.json()["assignees"]] == [installed.seat.user.id]


async def test_an_assignee_named_by_row_id_or_foreign_reference_is_refused(
    client, session, acting_user, role_session
):
    installed = await install_app(session, acting_user, role_session, granted=WRITE)
    headers = install_headers(installed, WRITE)
    gid = installed.guild.id
    seat_ref = await _reference_for_seat(client, session, installed, headers)
    project_id = await _own_project(client, installed, headers, "The app's")

    for named in (installed.seat.user.id, seat_ref[:-2] + "zz"):
        response = await client.post(
            _g(gid, "/tasks/"),
            headers=headers,
            json={"project_id": project_id, "title": "No", "assignee_ids": [named]},
        )
        assert response.status_code == 422, response.text


async def test_updates_moves_and_ticks_what_it_may_write(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_app(session, acting_user, role_session, granted=WRITE)
    headers = install_headers(installed, WRITE)
    gid = installed.guild.id
    seat_ref = await _reference_for_seat(client, session, installed, headers)
    first = await _own_project(client, installed, headers, "First")
    second = await _own_project(client, installed, headers, "Second")

    created = await client.post(
        _g(gid, "/tasks/"),
        headers=headers,
        json={"project_id": first, "title": "Draft", "checklist": [{"text": "a"}]},
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    item_id = created.json()["checklist"][0]["id"]

    updated = await client.patch(
        _g(gid, f"/tasks/{task_id}"),
        headers=headers,
        json={"title": "Final", "priority": "urgent", "assignee_ids": [seat_ref]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "Final"
    assert [a["id"] for a in updated.json()["assignees"]] == [seat_ref]
    assert_names_nobody(updated.text, [installed.seat.user.id, gid])

    await route_session_to_guild(session, gid)
    lines = await _assignment_lines(session, installed.seat.user.id)
    assert [line.data["assigned_by_name"] for line in lines] == [installed.app.name]

    ticked = await client.patch(
        _g(gid, f"/tasks/{task_id}/checklist/{item_id}"),
        headers=headers,
        json={"done": True},
    )
    assert ticked.status_code == 200, ticked.text
    assert [(i["id"], i["done"]) for i in ticked.json()] == [(item_id, True)]

    moved = await client.post(
        _g(gid, f"/tasks/{task_id}/move"),
        headers=headers,
        json={"target_project_id": second},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["project_id"] == second

    got = await client.get(_g(gid, f"/tasks/{task_id}"), headers=headers)
    assert got.status_code == 200, got.text
    assert got.json()["project_id"] == second
    assert_names_nobody(got.text, [installed.seat.user.id, gid])


async def test_a_task_in_a_project_it_only_reads_is_not_its_to_change(
    client, session, acting_user, role_session
):
    installed = await install_app(session, acting_user, role_session, granted=WRITE)
    project = await create_project(session, installed.placed, installed.seat.user)
    await _share(session, installed.guild.id, project)
    task = await create_task(session, project, title="Theirs")
    headers = install_headers(installed, WRITE)

    response = await client.patch(
        _g(installed.guild.id, f"/tasks/{task.id}"),
        headers=headers,
        json={"title": "Mine now"},
    )
    assert response.status_code == 403, response.text


async def test_a_person_valued_property_takes_a_reference(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    # The definition is the initiative's, and the person it names has to be
    # one of the initiative's members.
    scopes = [*WRITE, "initiatives:read", "members:read"]
    installed = await install_app(session, acting_user, role_session, granted=scopes)
    headers = install_headers(installed, scopes)
    gid = installed.guild.id
    seat_ref = await _reference_for_seat(client, session, installed, headers)
    project_id = await _own_project(client, installed, headers, "The app's")
    owner = await create_property_definition(
        session, installed.placed, name="Owner", type=PropertyType.user_reference
    )

    created = await client.post(
        _g(gid, "/tasks/"),
        headers=headers,
        json={
            "project_id": project_id,
            "title": "Owned",
            "property_values": [{"property_id": owner.id, "value": seat_ref}],
        },
    )
    assert created.status_code == 201, created.text
    [value] = created.json()["properties"]
    assert value["value"]["id"] == seat_ref
    assert_names_nobody(created.text, [installed.seat.user.id, gid])

    by_row_id = await client.patch(
        _g(gid, f"/tasks/{created.json()['id']}"),
        headers=headers,
        json={
            "property_values": [
                {"property_id": owner.id, "value": installed.seat.user.id}
            ]
        },
    )
    assert by_row_id.status_code == 422, by_row_id.text
    assert by_row_id.json()["detail"] == AppMessages.REFERENCE_UNKNOWN
