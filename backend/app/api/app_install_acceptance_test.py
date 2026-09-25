"""The routes an installed app calls, end to end on the real-role client.

Each test installs an app the way a community does (``install_app``: placed in
initiative A and not in B, granted scopes by the seat, registered by the
operator), seals an installation token for it, and calls ordinary
``/c/{guild_id}/…`` routes with that token. Postgres decides what the install
reaches; these tests hold the routes to the acceptance list of
``history/app-principal-design.md`` §6: reach, narrowing, live revocation,
authorship, the identity boundary, route opt-in and round trips.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlmodel import select

from app.api import actor_route
from app.api.actor_route import ActorRoute
from app.api.deps import route_app_scopes
from app.core.identity_boundary import BoundaryPhase
from app.core.app_scopes import ALL_SCOPES
from app.core.messages import AppMessages
from app.main import app
from app.models.platform.guild import Guild, GuildRole, GuildStatus
from app.models.tenant.app_placement import AppPlacement
from app.models.tenant.document import Document
from app.models.tenant.guild_app import GuildApp
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.services.marketplace import app_refs
from app.testing import (
    create_comment,
    create_document,
    create_guild_calendar,
    create_project,
    create_task,
    route_as,
    route_as_install,
    route_session_to_guild,
)
from app.testing.app_clients import (
    CLIENT,
    assert_names_nobody,
    install_app,
    install_headers,
    lift_person_and_guild_ids,
    share_with_members,
)


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _cold_reference_cache():
    app_refs.forget_cached_install_refs()
    yield
    app_refs.forget_cached_install_refs()


def _g(guild_id: int, path: str) -> str:
    return f"/api/v1/c/{guild_id}{path}"


async def _seat_session(installed: Any, role_session: Any) -> Any:
    """A request-path session routed as the community's seat holder."""
    s = await role_session("app_user")
    await route_as(s, user_id=installed.seat.user.id, guild_id=installed.guild.id)
    return s


@contextmanager
def _counting() -> Iterator[list[str]]:
    """Every statement any engine runs meanwhile, in order."""
    statements: list[str] = []

    def count(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", count)
    try:
        yield statements
    finally:
        event.remove(Engine, "before_cursor_execute", count)


# ---------------------------------------------------------------------------
# Reach
# ---------------------------------------------------------------------------


async def test_reads_the_documents_open_to_its_initiative(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    shared = await create_document(
        session, installed.placed, installed.seat.user, name="Open in A"
    )
    await share_with_members(session, shared, installed.placed.id)
    await create_document(
        session, installed.placed, installed.seat.user, name="Private in A"
    )
    in_b = await create_document(
        session, installed.unplaced, installed.seat.user, name="Open in B"
    )
    await share_with_members(session, in_b, installed.unplaced.id)
    headers = install_headers(installed, ["documents:read"])

    listed = await client.get(_g(installed.guild.id, "/documents/"), headers=headers)
    assert listed.status_code == 200, listed.text
    assert [d["name"] for d in listed.json()["items"]] == ["Open in A"]

    read = await client.get(
        _g(installed.guild.id, f"/documents/{shared.id}"), headers=headers
    )
    assert read.status_code == 200, read.text
    assert read.json()["name"] == "Open in A"
    assert read.json()["my_permission_level"] == "read"

    other = await client.get(
        _g(installed.guild.id, f"/documents/{in_b.id}"), headers=headers
    )
    assert other.status_code == 404, other.text


# ---------------------------------------------------------------------------
# Authorship and the boundary (documents)
# ---------------------------------------------------------------------------


async def test_what_it_creates_is_its_own_and_names_nobody(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:write"]
    )
    headers = install_headers(installed, ["documents:write"])

    created = await client.post(
        _g(installed.guild.id, "/documents/"),
        headers=headers,
        json={"name": "Made by the app", "initiative_id": installed.placed.id},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["created_by"] is None
    assert isinstance(body["guild_id"], str)
    assert body["my_permission_level"] == "owner"
    assert_names_nobody(created.text, [installed.seat.user.id, installed.guild.id])

    await route_session_to_guild(session, installed.guild.id)
    grants = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == "document",
                ResourceGrant.resource_id == body["id"],
            )
        )
    ).all()
    assert [(g.level, g.app_install_id, g.user_id) for g in grants] == [
        (ResourceAccessLevel.owner, installed.app.id, None)
    ]
    document = await session.get(Document, body["id"])
    assert document is not None and document.created_by is None


async def test_a_document_a_person_made_names_them_by_reference(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    shared = await create_document(
        session, installed.placed, installed.seat.user, name="Theirs"
    )
    await share_with_members(session, shared, installed.placed.id)
    headers = install_headers(installed, ["documents:read"])

    read = await client.get(
        _g(installed.guild.id, f"/documents/{shared.id}"), headers=headers
    )
    assert read.status_code == 200, read.text
    body = read.json()
    assert isinstance(body["created_by"], str)
    assert body["owner"]["id"] == body["created_by"]
    # Without sharing:read the install is shown who owns it, not the grants.
    assert body["grants"] == []
    assert_names_nobody(read.text, [installed.seat.user.id, installed.guild.id])

    listed = await client.get(_g(installed.guild.id, "/documents/"), headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["created_by"] == body["created_by"]
    assert_names_nobody(listed.text, [installed.seat.user.id, installed.guild.id])

    # A person reading the same document is served row ids, as always.
    person = await client.get(
        _g(installed.guild.id, f"/documents/{shared.id}"),
        headers=installed.seat.headers,
    )
    assert person.status_code == 200, person.text
    assert person.json()["created_by"] == installed.seat.user.id
    assert person.json()["guild_id"] == installed.guild.id


# ---------------------------------------------------------------------------
# Reach, continued
# ---------------------------------------------------------------------------


async def _grant_to_install(
    session: Any, installed: Any, document: Document, level: ResourceAccessLevel
) -> None:
    """Share ``document`` with the install, the way the seat's grant would."""
    await route_session_to_guild(session, installed.guild.id)
    session.add(
        ResourceGrant(
            resource_type="document",
            resource_id=document.id,
            app_install_id=installed.app.id,
            level=level,
            initiative_id=document.initiative_id,
        )
    )
    await session.commit()


async def test_a_private_document_is_read_only_once_shared_with_the_app(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    private = await create_document(
        session, installed.placed, installed.seat.user, name="Private in A"
    )
    headers = install_headers(installed, ["documents:read"])
    url = _g(installed.guild.id, f"/documents/{private.id}")

    assert (await client.get(url, headers=headers)).status_code == 404

    await _grant_to_install(session, installed, private, ResourceAccessLevel.read)
    read = await client.get(url, headers=headers)
    assert read.status_code == 200, read.text
    assert read.json()["my_permission_level"] == "read"


async def test_it_cannot_write_even_what_is_shared_with_it_at_write(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    document = await create_document(
        session, installed.placed, installed.seat.user, name="Shared at write"
    )
    await _grant_to_install(session, installed, document, ResourceAccessLevel.write)
    url = _g(installed.guild.id, f"/documents/{document.id}")

    # A token that asks for the read scope only.
    refused = await client.patch(
        url,
        headers=install_headers(installed, ["documents:read"]),
        json={"name": "Renamed"},
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == AppMessages.SCOPE_REQUIRED

    # A token claiming a write scope the seat never granted is held to the
    # grant: the standing holds no write.
    claimed = await client.patch(
        url,
        headers=install_headers(installed, ["documents:write"]),
        json={"name": "Renamed"},
    )
    assert claimed.status_code == 403, claimed.text

    await route_session_to_guild(session, installed.guild.id)
    await session.refresh(document)
    assert document.name == "Shared at write"


async def test_it_cannot_create_a_project(client, session, acting_user, role_session):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    response = await client.post(
        _g(installed.guild.id, "/projects/"),
        headers=install_headers(installed, ["documents:read"]),
        json={"name": "Nope", "initiative_id": installed.placed.id},
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == AppMessages.SCOPE_REQUIRED


async def test_the_role_refuses_guild_settings_outright(
    session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    s = await role_session("app_user")
    await route_as_install(
        s,
        guild_id=installed.guild.id,
        install_id=installed.app.id,
        client_id=CLIENT,
        scopes=["documents:read"],
    )
    with pytest.raises(DBAPIError, match="permission denied"):
        await s.exec(text("SELECT count(*) FROM guild_settings"))


# ---------------------------------------------------------------------------
# Narrowing
# ---------------------------------------------------------------------------


async def test_a_narrowed_token_reads_only_its_initiative(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session,
        acting_user,
        role_session,
        granted=["documents:read", "calendars:read"],
    )
    # Placed in B too, so only the narrowing keeps B out.
    await route_session_to_guild(session, installed.guild.id)
    session.add(
        AppPlacement(install_id=installed.app.id, initiative_id=installed.unplaced.id)
    )
    await session.commit()
    in_a = await create_document(
        session, installed.placed, installed.seat.user, name="In A"
    )
    await share_with_members(session, in_a, installed.placed.id)
    in_b = await create_document(
        session, installed.unplaced, installed.seat.user, name="In B"
    )
    await share_with_members(session, in_b, installed.unplaced.id)
    await create_guild_calendar(
        session, installed.guild, installed.seat.user, name="Community"
    )
    scopes = ["documents:read", "calendars:read"]
    wide = install_headers(installed, scopes)
    narrow = install_headers(installed, scopes, initiative_id=installed.placed.id)
    guild = installed.guild.id

    everything = await client.get(_g(guild, "/documents/"), headers=wide)
    assert sorted(d["name"] for d in everything.json()["items"]) == ["In A", "In B"]

    only_a = await client.get(_g(guild, "/documents/"), headers=narrow)
    assert [d["name"] for d in only_a.json()["items"]] == ["In A"]
    assert (
        await client.get(_g(guild, f"/documents/{in_b.id}"), headers=narrow)
    ).status_code == 404

    community = await client.get(_g(guild, "/calendars/"), headers=wide)
    assert "Community" in [c["name"] for c in community.json()["items"]]
    narrowed = await client.get(_g(guild, "/calendars/"), headers=narrow)
    assert "Community" not in [c["name"] for c in narrowed.json()["items"]]


# ---------------------------------------------------------------------------
# Live revocation
# ---------------------------------------------------------------------------


async def _open_document(session: Any, installed: Any) -> Document:
    document = await create_document(
        session, installed.placed, installed.seat.user, name="Open in A"
    )
    await share_with_members(session, document, installed.placed.id)
    return document


async def _names(client: Any, installed: Any, headers: dict[str, str]) -> Any:
    response = await client.get(_g(installed.guild.id, "/documents/"), headers=headers)
    if response.status_code != 200:
        return response.status_code
    return [d["name"] for d in response.json()["items"]]


async def test_removing_the_placement_takes_effect_on_the_next_request(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    await _open_document(session, installed)
    headers = install_headers(installed, ["documents:read"])
    assert await _names(client, installed, headers) == ["Open in A"]

    await route_session_to_guild(session, installed.guild.id)
    placement = await session.get(AppPlacement, (installed.app.id, installed.placed.id))
    await session.delete(placement)
    await session.commit()

    assert await _names(client, installed, headers) == []


async def test_removing_the_scope_takes_effect_on_the_next_request(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    await _open_document(session, installed)
    headers = install_headers(installed, ["documents:read"])
    assert await _names(client, installed, headers) == ["Open in A"]

    s = await _seat_session(installed, role_session)
    row = (await s.exec(select(GuildApp).where(GuildApp.id == installed.app.id))).one()
    row.granted_scopes = []
    s.add(row)
    await s.commit()

    assert await _names(client, installed, headers) == 403


@pytest.mark.parametrize("switch", ["registration", "install", "guild"])
async def test_switching_off_takes_effect_on_the_next_request(
    client, session, acting_user, role_session, switch
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    await _open_document(session, installed)
    headers = install_headers(installed, ["documents:read"])
    assert await _names(client, installed, headers) == ["Open in A"]

    if switch == "registration":
        await session.exec(
            text(
                "UPDATE public.app_service_registrations SET enabled = false "
                "WHERE public_id = :c"
            ),
            params={"c": CLIENT},
        )
    elif switch == "install":
        await route_session_to_guild(session, installed.guild.id)
        await session.exec(
            text("UPDATE guild_apps SET enabled = false WHERE id = :i"),
            params={"i": installed.app.id},
        )
    else:
        guild = await session.get(Guild, installed.guild.id)
        assert guild is not None
        guild.status = GuildStatus.suspended
        session.add(guild)
    await session.commit()

    assert await _names(client, installed, headers) == 401


# ---------------------------------------------------------------------------
# Route opt-in
# ---------------------------------------------------------------------------


async def test_an_unmarked_route_refuses_an_installation_token(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    response = await client.get(
        _g(installed.guild.id, "/documents/counts"),
        headers=install_headers(installed, ["documents:read"]),
    )
    assert response.status_code == 401, response.text


def test_every_marked_route_names_scopes_in_the_vocabulary():
    marked = [route for route in app.routes if route_app_scopes(route)]
    assert marked, "no route names an app scope"
    unknown = {
        (getattr(route, "path", "?"), scope)
        for route in marked
        for scope in route_app_scopes(route)
        if scope not in ALL_SCOPES
    }
    assert not unknown, unknown
    assert all(isinstance(route, ActorRoute) for route in marked)


# ---------------------------------------------------------------------------
# Round trips
# ---------------------------------------------------------------------------


@contextmanager
def _handler_start(monkeypatch: Any, statements: list[str]) -> Iterator[list[int]]:
    """Record how many statements had run when the route's own code began."""
    seen: list[int] = []
    original = actor_route._enter

    def enter(phase: Any) -> Any:
        if phase is BoundaryPhase.handler:
            seen.append(len(statements))
        return original(phase)

    monkeypatch.setattr(actor_route, "_enter", enter)
    yield seen


async def test_a_list_costs_two_statements_before_its_handler(
    client, session, acting_user, role_session, monkeypatch
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    await _open_document(session, installed)
    headers = install_headers(installed, ["documents:read"])

    with _counting() as statements, _handler_start(monkeypatch, statements) as seen:
        response = await client.get(
            _g(installed.guild.id, "/documents/"), headers=headers
        )
    assert response.status_code == 200, response.text
    assert seen == [2], statements[:4]


async def test_a_response_naming_people_costs_one_statement_cold_and_none_warm(
    client, session, acting_user, role_session, monkeypatch
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    document = await _open_document(session, installed)
    headers = install_headers(installed, ["documents:read"])
    url = _g(installed.guild.id, f"/documents/{document.id}")

    # Mint the references once, then measure a warm read against a cold one.
    first = await client.get(url, headers=headers)
    assert first.status_code == 200, first.text
    with _counting() as warm:
        again = await client.get(url, headers=headers)
    assert again.json() == first.json()

    app_refs.forget_cached_install_refs()
    with _counting() as cold:
        third = await client.get(url, headers=headers)
    assert third.json() == first.json()
    assert len(cold) == len(warm) + 1, (cold, warm)


# ---------------------------------------------------------------------------
# People (members:read)
# ---------------------------------------------------------------------------


async def test_member_search_names_members_by_reference_and_carries_no_address(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_app(
        session, acting_user, role_session, granted=["members:read"]
    )
    elsewhere = await acting_user(guild_role=GuildRole.member)
    headers = install_headers(installed, ["members:read"])

    response = await client.get(
        _g(installed.guild.id, "/users/search"), headers=headers
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["username"] for item in items] == [installed.seat.user.username]
    assert all(isinstance(item["id"], str) for item in items)
    assert "email" not in response.text
    assert_names_nobody(
        response.text,
        [installed.seat.user.id, elsewhere.user.id, installed.guild.id],
    )

    # The reference resolves a known selection, as a row id does for a person.
    ref = items[0]["id"]
    picked = await client.get(
        _g(installed.guild.id, "/users/search"),
        headers=headers,
        params={"user_id": ref},
    )
    assert [item["id"] for item in picked.json()["items"]] == [ref]

    # A row id, or somebody outside its sector, names nobody.
    unknown = await client.get(
        _g(installed.guild.id, "/users/search"),
        headers=headers,
        params={"user_id": str(elsewhere.user.id)},
    )
    assert unknown.status_code == 422, unknown.text


async def test_member_search_narrows_to_an_initiative_the_install_is_placed_in(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["members:read"]
    )
    inside = await acting_user(
        guild_role=GuildRole.member,
        guild=installed.guild,
        initiative=installed.placed,
        initiative_role="member",
    )
    outside = await acting_user(guild_role=GuildRole.member, guild=installed.guild)
    headers = install_headers(installed, ["members:read"])
    url = _g(installed.guild.id, "/users/search")

    narrowed = await client.get(
        url, headers=headers, params={"initiative_id": installed.placed.id}
    )
    assert narrowed.status_code == 200, narrowed.text
    names = {item["username"] for item in narrowed.json()["items"]}
    assert inside.user.username in names
    assert outside.user.username not in names

    unplaced = await client.get(
        url, headers=headers, params={"initiative_id": installed.unplaced.id}
    )
    assert unplaced.status_code == 403, unplaced.text


async def test_member_search_needs_members_read(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    response = await client.get(
        _g(installed.guild.id, "/users/search"),
        headers=install_headers(installed, ["documents:read"]),
    )
    assert response.status_code == 403, response.text


async def test_a_write_naming_three_people_costs_the_same_two(
    client, session, acting_user, role_session, monkeypatch
):
    scopes = ["projects:write", "members:read"]
    installed = await install_app(session, acting_user, role_session, granted=scopes)
    for _ in range(3):
        await acting_user(
            guild_role=GuildRole.member,
            guild=installed.guild,
            initiative=installed.placed,
            initiative_role="member",
        )
    headers = install_headers(installed, scopes)
    guild = installed.guild.id

    project = await client.post(
        _g(guild, "/projects/"),
        headers=headers,
        json={"name": "The app's", "initiative_id": installed.placed.id},
    )
    assert project.status_code == 201, project.text
    members = await client.get(_g(guild, "/users/search"), headers=headers)
    refs = [item["id"] for item in members.json()["items"]]
    others = [ref for ref in refs][:3]
    assert len(others) == 3

    with _counting() as statements, _handler_start(monkeypatch, statements) as seen:
        created = await client.post(
            _g(guild, "/tasks/"),
            headers=headers,
            json={
                "project_id": project.json()["id"],
                "title": "Three of them",
                "assignee_ids": others,
            },
        )
    assert created.status_code == 201, created.text
    assert seen == [2], statements[:4]
    assert sorted(a["id"] for a in created.json()["assignees"]) == sorted(others)


# ---------------------------------------------------------------------------
# Search suggestions
# ---------------------------------------------------------------------------


async def _open_project(session: Any, installed: Any, initiative: Any, name: str):
    """A project in ``initiative`` shared with every member of it, which an
    install placed there counts as."""
    project = await create_project(session, initiative, installed.seat.user, name=name)
    session.add(
        ResourceGrant(
            resource_type="project",
            resource_id=project.id,
            all_initiative_members=True,
            level=ResourceAccessLevel.read,
            initiative_id=initiative.id,
        )
    )
    await session.commit()
    return project


async def _suggest(client: Any, installed: Any, headers: dict[str, str], **params):
    return await client.get(
        _g(installed.guild.id, "/search/suggest"), headers=headers, params=params
    )


async def test_suggests_only_the_tasks_it_could_read(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["projects:read"]
    )
    open_a = await _open_project(session, installed, installed.placed, "Open A")
    private_a = await create_project(
        session, installed.placed, installed.seat.user, name="Private A"
    )
    open_b = await _open_project(session, installed, installed.unplaced, "Open B")
    readable = await create_task(session, open_a, title="harbor open")
    await create_task(session, private_a, title="harbor private")
    await create_task(session, open_b, title="harbor elsewhere")
    headers = install_headers(installed, ["projects:read"])

    response = await _suggest(client, installed, headers, q="harbor", types=["task"])
    assert response.status_code == 200, response.text
    rows = response.json()
    assert [r["entity_id"] for r in rows] == [readable.id]
    assert rows[0]["tool_id"] == open_a.id
    assert rows[0]["initiative_id"] == installed.placed.id
    assert rows[0]["can_write"] is False

    # No types: the default scope, narrowed to what it may read.
    unnamed = await _suggest(client, installed, headers, q="harbor")
    assert unnamed.status_code == 200, unnamed.text
    assert [r["entity_id"] for r in unnamed.json()] == [readable.id]


async def test_suggest_leaves_out_the_kinds_it_holds_no_scope_for(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["projects:read"]
    )
    project = await _open_project(session, installed, installed.placed, "Open A")
    task = await create_task(session, project, title="lantern task")
    document = await create_document(
        session, installed.placed, installed.seat.user, name="lantern doc"
    )
    await share_with_members(session, document, installed.placed.id)
    headers = install_headers(installed, ["projects:read"])

    both = await _suggest(
        client, installed, headers, q="lantern", types=["task", "document"]
    )
    assert both.status_code == 200, both.text
    assert [r["entity_id"] for r in both.json()] == [task.id]

    refused = await _suggest(
        client, installed, headers, q="lantern", types=["document"]
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == AppMessages.SCOPE_REQUIRED


async def test_suggest_asks_the_scope_of_the_tool_a_comment_is_on(
    client, session, acting_user, role_session
):
    """A comment on a task is read through the task's project, so finding one
    needs ``projects:read`` beside ``comments:read``."""
    installed = await install_app(
        session,
        acting_user,
        role_session,
        granted=["projects:read", "comments:read"],
    )
    project = await _open_project(session, installed, installed.placed, "Open A")
    task = await create_task(session, project, title="stage build")
    comment = await create_comment(
        session, installed.seat.user, task=task, content="beacon confirmed"
    )

    comments_only = await _suggest(
        client,
        installed,
        install_headers(installed, ["comments:read"]),
        q="beacon",
        types=["comment"],
    )
    assert comments_only.status_code == 200, comments_only.text
    assert comments_only.json() == []

    with_projects = await _suggest(
        client,
        installed,
        install_headers(installed, ["comments:read", "projects:read"]),
        q="beacon",
        types=["comment"],
    )
    assert with_projects.status_code == 200, with_projects.text
    assert [r["entity_id"] for r in with_projects.json()] == [comment.id]


async def test_a_narrowed_token_suggests_only_its_initiative(
    client, session, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["projects:read"]
    )
    # Placed in B too, so only the narrowing keeps B out.
    await route_session_to_guild(session, installed.guild.id)
    session.add(
        AppPlacement(install_id=installed.app.id, initiative_id=installed.unplaced.id)
    )
    await session.commit()
    in_a = await create_task(
        session,
        await _open_project(session, installed, installed.placed, "Open A"),
        title="orchard in a",
    )
    in_b = await create_task(
        session,
        await _open_project(session, installed, installed.unplaced, "Open B"),
        title="orchard in b",
    )
    scopes = ["projects:read"]

    wide = await _suggest(
        client, installed, install_headers(installed, scopes), q="orchard"
    )
    assert wide.status_code == 200, wide.text
    assert sorted(r["entity_id"] for r in wide.json()) == sorted([in_a.id, in_b.id])

    narrow = await _suggest(
        client,
        installed,
        install_headers(installed, scopes, initiative_id=installed.placed.id),
        q="orchard",
    )
    assert narrow.status_code == 200, narrow.text
    assert [r["entity_id"] for r in narrow.json()] == [in_a.id]

    # Asking for the other initiative by name finds nothing either.
    asked_b = await _suggest(
        client,
        installed,
        install_headers(installed, scopes, initiative_id=installed.placed.id),
        q="orchard",
        initiative_id=installed.unplaced.id,
    )
    assert asked_b.status_code == 200, asked_b.text
    assert asked_b.json() == []
