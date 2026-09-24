"""The custom property routes an installed app calls.

``PUT /{documents,tasks,calendar-events}/{id}/properties`` answer to the write
scope of the tool that governs the item, and a person-valued property names the
person by the install's own reference for them, on the way in and on the way
out.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.core.messages import AppMessages, QueryMessages
from app.models.tenant.property import PropertyType
from app.services.marketplace import app_refs
from app.testing import (
    create_guild_app,
    create_property_definition,
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
    return f"/api/v1/g/{guild_id}{path}"


async def _document(client: Any, session: Any, installed: Any, headers: dict) -> int:
    created = await client.post(
        _g(installed.guild.id, "/documents/"),
        headers=headers,
        json={"name": "The app's", "initiative_id": installed.placed.id},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def _task(client: Any, session: Any, installed: Any, headers: dict) -> int:
    project = await client.post(
        _g(installed.guild.id, "/projects/"),
        headers=headers,
        json={"name": "The app's", "initiative_id": installed.placed.id},
    )
    assert project.status_code == 201, project.text
    task = await client.post(
        _g(installed.guild.id, "/tasks/"),
        headers=headers,
        json={"project_id": project.json()["id"], "title": "The app's"},
    )
    assert task.status_code == 201, task.text
    return task.json()["id"]


async def _event(client: Any, session: Any, installed: Any, headers: dict) -> int:
    await route_session_to_guild(session, guild_of(installed.placed))
    installed.placed.calendars_enabled = True
    session.add(installed.placed)
    await session.commit()
    calendar = await client.post(
        _g(installed.guild.id, "/calendars/"),
        headers=headers,
        json={"name": "The app's", "initiative_id": installed.placed.id},
    )
    assert calendar.status_code == 201, calendar.text
    start = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=1)
    event = await client.post(
        _g(installed.guild.id, "/calendar-events/"),
        headers=headers,
        json={
            "calendar_id": calendar.json()["id"],
            "title": "The app's",
            "start_at": start.isoformat(),
            "end_at": (start + timedelta(hours=1)).isoformat(),
        },
    )
    assert event.status_code == 201, event.text
    return event.json()["id"]


#: Per kind: the tool's scopes, how to make an item the install may write, its
#: route, and the response field its values come back in.
_KINDS = {
    "documents": ("documents", _document, "/documents", "properties"),
    "tasks": ("projects", _task, "/tasks", "properties"),
    "calendar-events": ("calendars", _event, "/calendar-events", "property_values"),
}


async def _seat_reference(client: Any, installed: Any, headers: dict) -> str:
    """What the install calls the seat, a member of the initiative it is
    placed in."""
    members = await client.get(_g(installed.guild.id, "/users/search"), headers=headers)
    assert members.status_code == 200, members.text
    [seat] = members.json()["items"]
    assert isinstance(seat["id"], str)
    return seat["id"]


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", list(_KINDS))
async def test_setting_values_needs_the_tools_write(
    kind, client, session, acting_user, role_session
):
    tool = _KINDS[kind][0]
    scopes = [f"{tool}:read", f"{tool}:write", "initiatives:read"]
    installed = await install_app(session, acting_user, role_session, granted=scopes)
    guild_id = installed.guild.id
    item_id = await _KINDS[kind][1](
        client, session, installed, install_headers(installed, scopes)
    )
    note = await create_property_definition(
        session, installed.placed, name="Note", type=PropertyType.text
    )
    url = _g(guild_id, f"{_KINDS[kind][2]}/{item_id}/properties")
    body = {"values": [{"property_id": note.id, "value": "Set by the app"}]}

    read_only = await client.put(
        url, headers=install_headers(installed, [f"{tool}:read"]), json=body
    )
    assert read_only.status_code == 403, read_only.text
    assert read_only.json()["detail"] == AppMessages.SCOPE_REQUIRED

    written = await client.put(
        url, headers=install_headers(installed, scopes), json=body
    )
    assert written.status_code == 200, written.text
    [value] = written.json()[_KINDS[kind][3]]
    assert value["property_id"] == note.id
    assert value["value"] == "Set by the app"


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", list(_KINDS))
async def test_a_person_valued_property_is_set_and_read_by_reference(
    kind, client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    tool = _KINDS[kind][0]
    # The person has to be a member of the item's initiative, which the
    # service reads from the roster.
    scopes = [f"{tool}:read", f"{tool}:write", "initiatives:read", "members:read"]
    installed = await install_app(session, acting_user, role_session, granted=scopes)
    headers = install_headers(installed, scopes)
    guild_id = installed.guild.id
    item_id = await _KINDS[kind][1](client, session, installed, headers)
    owner = await create_property_definition(
        session, installed.placed, name="Owner", type=PropertyType.user_reference
    )
    seat_ref = await _seat_reference(client, installed, headers)
    path = f"{_KINDS[kind][2]}/{item_id}"

    written = await client.put(
        _g(guild_id, f"{path}/properties"),
        headers=headers,
        json={"values": [{"property_id": owner.id, "value": seat_ref}]},
    )
    assert written.status_code == 200, written.text
    [value] = written.json()[_KINDS[kind][3]]
    assert value["value"]["id"] == seat_ref
    assert_names_nobody(written.text, [installed.seat.user.id, guild_id])

    read = await client.get(_g(guild_id, path), headers=headers)
    assert read.status_code == 200, read.text
    [value] = read.json()[_KINDS[kind][3]]
    assert value["value"]["id"] == seat_ref
    assert_names_nobody(read.text, [installed.seat.user.id, guild_id])

    # A person reads the same value as the row id it is stored as.
    as_person = await client.get(_g(guild_id, path), headers=installed.seat.headers)
    assert as_person.status_code == 200, as_person.text
    [value] = as_person.json()[_KINDS[kind][3]]
    assert value["value"]["id"] == installed.seat.user.id


async def test_a_person_named_any_other_way_is_a_422(
    client, session, acting_user, role_session
):
    scopes = ["documents:read", "documents:write", "initiatives:read", "members:read"]
    installed = await install_app(session, acting_user, role_session, granted=scopes)
    headers = install_headers(installed, scopes)
    guild_id = installed.guild.id
    document_id = await _document(client, session, installed, headers)
    owner = await create_property_definition(
        session, installed.placed, name="Owner", type=PropertyType.user_reference
    )
    other = await create_guild_app(
        session,
        installed.guild,
        installed.seat.user,
        definition={
            "app_kind": "service",
            "service": {"public_id": "tests.token-client-two", "protocol": 1},
        },
        listing_uid="TOKENCLIENT002",
    )
    # The seat, as another install knows them.
    foreign = await app_refs.ensure_app_ref(
        guild_id=guild_id, app_install_id=other.id, user_id=installed.seat.user.id
    )

    for named in (foreign, installed.seat.user.id, "uapp_" + "x" * 32):
        response = await client.put(
            _g(guild_id, f"/documents/{document_id}/properties"),
            headers=headers,
            json={"values": [{"property_id": owner.id, "value": named}]},
        )
        assert response.status_code == 422, (named, response.text)
        assert response.json()["detail"] == AppMessages.REFERENCE_UNKNOWN


async def test_a_document_list_filter_that_names_a_person_is_refused(
    client, session, acting_user, role_session
):
    scopes = ["documents:read", "documents:write", "initiatives:read", "members:read"]
    installed = await install_app(session, acting_user, role_session, granted=scopes)
    headers = install_headers(installed, scopes)
    guild_id = installed.guild.id
    await _document(client, session, installed, headers)
    owner = await create_property_definition(
        session, installed.placed, name="Owner", type=PropertyType.user_reference
    )

    def _filters(op: str, value: Any) -> dict:
        return {
            "property_filters": json.dumps(
                [{"property_id": owner.id, "op": op, "value": value}]
            )
        }

    named = await client.get(
        _g(guild_id, "/documents/"),
        headers=headers,
        params=_filters("eq", installed.seat.user.id),
    )
    assert named.status_code == 400, named.text
    assert named.json()["detail"] == QueryMessages.INVALID_CONDITIONS

    # Asking whether anyone is set names nobody.
    unset = await client.get(
        _g(guild_id, "/documents/"), headers=headers, params=_filters("is_null", True)
    )
    assert unset.status_code == 200, unset.text

    # A person filters by the row id as before.
    as_person = await client.get(
        _g(guild_id, "/documents/"),
        headers=installed.seat.headers,
        params=_filters("eq", installed.seat.user.id),
    )
    assert as_person.status_code == 200, as_person.text
