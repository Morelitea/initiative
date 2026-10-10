"""An initiative's views of a tool, and who may change them.

Reading follows reading the instance (or being in the initiative, for a shared
page). Changing a project's set takes the right to configure it — its owner, a
manager of the initiative or a guild admin — with write access to it; changing
a shared page's takes managing the initiative.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import DBAPIError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.advisory_locks import LockNamespace, advisory_lock
from app.models.platform.guild import CommunityRole
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.models.tenant.tool_view import ToolView
from app.schemas.tenant.tool_view import (
    MAX_DEPTH,
    MAX_NODES,
    MAX_PLUGIN_PARTS,
    MAX_VIEWS,
)
from app.services.tenant import tool_views as tool_views_service
from app.testing import create_project, create_resource_grant, route_session_to_guild


def _project(a: Any) -> dict[str, Any]:
    return {"tool": "project", "tool_id": a.project.id}


def _view(name: str, layout: str = "table", **extra: Any) -> dict[str, Any]:
    definition = {"layout": {"type": layout}, **extra.pop("definition", {})}
    return {"name": name, "definition": definition, **extra}


def _set(*views: dict[str, Any]) -> dict[str, Any]:
    return {"views": list(views)}


_TWO = _set(
    _view("Table", slug="table"),
    _view(
        "Sprint",
        "board",
        is_default=True,
        definition={
            "filters": {"assignees": ["me"]},
            "card": {
                "type": "card",
                "children": [
                    {
                        "type": "stack",
                        "props": {"direction": "row", "gap": "sm", "wrap": True},
                        "children": [
                            {"type": "field", "props": {"field": "title"}},
                            {"type": "field", "props": {"field": "property:12"}},
                            {"type": "properties"},
                            {"type": "field", "props": {"field": "plugin:3:ci.state"}},
                            {
                                "type": "plugin",
                                "props": {"plugin": 3, "part": "builds"},
                            },
                        ],
                    }
                ],
            },
            "columns": ["title", "dueDate", "property:12", "plugin:3:ci.state"],
            "sort": [{"field": "dueDate", "direction": "desc"}],
            "opens": "page",
        },
    ),
)


async def test_a_project_shows_the_shipped_views_until_it_saves_some(
    client: AsyncClient, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )

    response = await client.get(a.g("/views/"), params=_project(a), headers=a.headers)

    assert response.status_code == 200
    body = response.json()
    assert (body["stored"], body["can_configure"], body["item_layouts"]) == (
        False,
        True,
        [],
    )
    assert [
        (v["slug"], v["is_default"], v["id"], v["definition"]["layout"]["type"])
        for v in body["views"]
    ] == [
        ("table", True, None, "table"),
        ("board", False, None, "board"),
        ("calendar", False, None, "calendar"),
        ("incomplete", False, None, "table"),
        ("unassigned", False, None, "table"),
        ("mine", False, None, "table"),
    ]
    filters = {v["slug"]: v["definition"]["filters"] for v in body["views"]}
    assert filters["table"] is None
    assert filters["incomplete"]["status_categories"] == [
        "backlog",
        "todo",
        "in_progress",
    ]
    assert (filters["unassigned"]["assignees"], filters["mine"]["assignees"]) == (
        ["none"],
        ["me"],
    )


#: A task's page: the side region left out is drawn as shipped.
_PAGE: dict[str, Any] = {
    "main": [
        {
            "type": "section",
            "props": {"title": "Work", "collapsed": True},
            "children": [
                {"type": "field", "props": {"field": "description"}},
                {"type": "plugin", "props": {"plugin": 3, "part": "builds"}},
            ],
        },
        {"type": "comments"},
    ],
    "side": [
        {
            "type": "stack",
            "props": {
                "direction": "row",
                "gap": "sm",
                "wrap": True,
                "align": "start",
                "tone": "muted",
            },
            "children": [{"type": "status"}, {"type": "dates"}],
        },
        {"type": "properties"},
    ],
}


async def test_saving_replaces_the_whole_set_and_deleting_returns_to_shipped(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    url, params = a.g("/views/"), _project(a)

    saved = await client.put(url, params=params, json=_TWO, headers=a.headers)
    assert saved.status_code == 200, saved.text
    read = (await client.get(url, params=params, headers=a.headers)).json()
    assert read == saved.json()
    assert read["stored"] is True
    assert [(v["slug"], v["position"], v["is_default"]) for v in read["views"]] == [
        ("table", 0, False),
        ("sprint", 1, True),
    ]
    await route_session_to_guild(session, a.guild.id)
    stored = await session.get(ToolView, read["views"][1]["id"])
    assert stored is not None
    assert stored.definition == _TWO["views"][1]["definition"]

    again = await client.put(
        url,
        params=params,
        json={
            **_set(_view("Only", "calendar", is_default=True)),
            "item_layouts": [{"item_kind": "task", "definition": _PAGE}],
        },
        headers=a.headers,
    )
    assert [v["slug"] for v in again.json()["views"]] == ["only"]
    assert [
        (layout["item_kind"], layout["definition"])
        for layout in again.json()["item_layouts"]
    ] == [("task", {"header": None, **_PAGE})]

    cleared = await client.delete(url, params=params, headers=a.headers)
    assert cleared.status_code == 204
    shipped = (await client.get(url, params=params, headers=a.headers)).json()
    assert shipped["stored"] is False
    assert [v["slug"] for v in shipped["views"]] == [
        "table",
        "board",
        "calendar",
        "incomplete",
        "unassigned",
        "mine",
    ]


async def test_saving_and_resetting_take_turns_on_the_target(
    client: AsyncClient, acting_user, monkeypatch
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    taken: list[tuple[LockNamespace, Any]] = []

    async def recording_lock(conn, namespace, key=None, **kwargs):
        taken.append((namespace, key))
        return await advisory_lock(conn, namespace, key, **kwargs)

    monkeypatch.setattr(tool_views_service, "advisory_lock", recording_lock)
    url, params = a.g("/views/"), _project(a)

    saved = await client.put(url, params=params, json=_TWO, headers=a.headers)
    reset = await client.delete(url, params=params, headers=a.headers)

    assert (saved.status_code, reset.status_code) == (200, 204)
    key = f"{a.guild.id}:project:{a.project.id}:{a.initiative.id}"
    assert taken == [(LockNamespace.TOOL_VIEWS, key)] * 2


@pytest.mark.parametrize("who", ["admin", "manager"])
async def test_an_admin_and_a_manager_with_write_may_configure(
    client: AsyncClient, session: AsyncSession, acting_user, who: str
):
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    if who == "admin":
        other = await acting_user(guild_role=CommunityRole.admin, guild=owner.guild)
    else:
        other = await acting_user(
            guild_role=CommunityRole.member,
            guild=owner.guild,
            initiative=owner.initiative,
            initiative_role="project_manager",
        )
        # Sharing still decides what a manager may change.
        await create_resource_grant(
            session, owner.project, user=other.user, level=ResourceAccessLevel.write
        )

    response = await client.put(
        other.g("/views/"), params=_project(owner), json=_TWO, headers=other.headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["can_configure"] is True


@pytest.mark.parametrize("level", [ResourceAccessLevel.write, ResourceAccessLevel.read])
async def test_a_member_who_cannot_configure_reads_but_cannot_save(
    client: AsyncClient, session: AsyncSession, acting_user, level
):
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    await create_resource_grant(session, owner.project, user=member.user, level=level)
    url, params = member.g("/views/"), _project(owner)

    listed = await client.get(url, params=params, headers=member.headers)
    saved = await client.put(url, params=params, json=_TWO, headers=member.headers)
    cleared = await client.delete(url, params=params, headers=member.headers)

    assert listed.json()["can_configure"] is False
    assert saved.status_code == 403
    assert saved.json()["detail"] == "PROJECT_CONFIGURE_REQUIRED"
    assert cleared.status_code == 403


async def test_a_non_member_of_the_initiative_reads_nothing(
    client: AsyncClient, acting_user, reading_as
):
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    outsider = await acting_user(guild_role=CommunityRole.member, guild=owner.guild)
    url, params = owner.g("/views/"), _project(owner)
    assert (
        await client.put(url, params=params, json=_TWO, headers=owner.headers)
    ).status_code == 200

    listed = await client.get(url, params=params, headers=outsider.headers)
    saved = await client.put(url, params=params, json=_TWO, headers=outsider.headers)
    assert (listed.status_code, saved.status_code) == (404, 404)

    for user, seen in ((outsider.user, 0), (owner.user, 2)):
        reader = await reading_as(user.id, owner.guild.id)
        assert len((await reader.exec(select(ToolView.id))).all()) == seen


async def test_an_initiatives_views_list_each_project_the_reader_can_open(
    client: AsyncClient, session: AsyncSession, acting_user
):
    manager = await acting_user(
        guild_role=CommunityRole.member,
        initiative=True,
        project=True,
        initiative_role="project_manager",
    )
    closed = await create_project(
        session, manager.initiative, manager.user, name="Zeta"
    )
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=manager.guild,
        initiative=manager.initiative,
        initiative_role="member",
    )
    await create_resource_grant(
        session, manager.project, user=member.user, level=ResourceAccessLevel.read
    )
    page = {"item_kind": "task", "definition": {"main": [{"type": "comments"}]}}
    assert (
        await client.put(
            manager.g("/views/"),
            params=_project(manager),
            json={**_TWO, "item_layouts": [page]},
            headers=manager.headers,
        )
    ).status_code == 200
    url, params = (
        manager.g("/views/initiative"),
        {"initiative_id": manager.initiative.id},
    )

    seen = (await client.get(url, params=params, headers=manager.headers)).json()
    read = (await client.get(url, params=params, headers=member.headers)).json()

    assert [
        (each["tool_id"], each["stored"], each["has_item_layout"]) for each in seen
    ] == [
        (manager.project.id, True, True),
        (closed.id, False, False),
    ]
    assert seen[0]["views"] == [
        {"name": "Table", "slug": "table", "layout": "table", "is_default": False},
        {"name": "Sprint", "slug": "sprint", "layout": "board", "is_default": True},
    ]
    assert seen[1]["views"][0] == {
        "name": "Table",
        "slug": "table",
        "layout": "table",
        "is_default": True,
    }
    assert all(each["can_configure"] for each in seen)
    # A member reads only what they were let into, and changes none of it.
    assert [(each["tool_id"], each["can_configure"]) for each in read] == [
        (manager.project.id, False)
    ]


async def test_an_initiatives_views_are_not_listed_outside_it(
    client: AsyncClient, acting_user
):
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    outsider = await acting_user(guild_role=CommunityRole.member, guild=owner.guild)

    response = await client.get(
        outsider.g("/views/initiative"),
        params={"initiative_id": owner.initiative.id},
        headers=outsider.headers,
    )

    assert response.status_code == 404


_FIELD = {"type": "field", "props": {"field": "title"}}


def _card(*children: dict[str, Any]) -> dict[str, Any]:
    return {"definition": {"card": {"type": "card", "children": list(children)}}}


def _deep(depth: int) -> dict[str, Any]:
    """A branch ``depth`` parts deep under a card."""
    node: dict[str, Any] = _FIELD
    for _ in range(depth - 1):
        node = {"type": "stack", "children": [node]}
    return node


def _field(field: str) -> dict[str, Any]:
    return {"type": "field", "props": {"field": field}}


def _plugin_part(plugin: int) -> dict[str, Any]:
    return {"type": "plugin", "props": {"plugin": plugin, "part": "builds"}}


def _one(**extra: Any) -> dict[str, Any]:
    return _set(_view("A", is_default=True, **extra))


@pytest.mark.parametrize(
    ("payload", "status", "detail"),
    [
        (_one(**_card({"type": "widget"})), 422, None),
        (_one(**_card({"type": "field", "props": {"field": "colour"}})), 422, None),
        (_one(definition={"columns": ["property:Size"]}), 422, None),
        (_one(definition={"columns": ["plugin:3:CI"]}), 422, None),
        (_one(**_card({"type": "comments"})), 422, None),
        (_one(definition={"columns": ["assignees"]}), 422, None),
        (_one(definition={"sort": [{"field": "property:12"}]}), 422, None),
        (_one(definition={"sort": [{"field": "comments"}]}), 422, None),
        (
            {
                **_one(),
                "item_layouts": [
                    {
                        "item_kind": "task",
                        "definition": {
                            "side": [{"type": "field", "props": {"field": "startDate"}}]
                        },
                    }
                ],
            },
            422,
            None,
        ),
        (
            {
                **_one(),
                "item_layouts": [
                    {
                        "item_kind": "task",
                        "definition": {
                            "side": [
                                {"type": "field", "props": {"field": "property:12"}}
                            ]
                        },
                    }
                ],
            },
            422,
            None,
        ),
        (
            {
                **_one(),
                "item_layouts": [
                    {"item_kind": "task", "definition": {"main": [{"type": "card"}]}}
                ],
            },
            422,
            None,
        ),
        (_one(definition={"columns": ["plugin:x:ci"]}), 422, None),
        (_one(**_card({"type": "plugin", "props": {"plugin": 3}})), 422, None),
        (
            _one(**_card(*[_plugin_part(3)] * (MAX_PLUGIN_PARTS + 1))),
            400,
            "TOOL_VIEWS_TOO_MANY_PLUGIN_PARTS",
        ),
        (_one(definition={"colour": 1}), 422, None),
        (_one(definition={"filters": {"assignees": ["everyone"]}}), 422, None),
        (_set(_view("A"), _view("B")), 400, "TOOL_VIEWS_ONE_DEFAULT"),
        (
            _set(_view("A", is_default=True), _view("B", is_default=True)),
            400,
            "TOOL_VIEWS_ONE_DEFAULT",
        ),
        (
            _set(_view("A", slug="x", is_default=True), _view("B", slug="x")),
            400,
            "TOOL_VIEWS_DUPLICATE_SLUG",
        ),
        (_one(**_card(*[_FIELD] * MAX_NODES)), 400, "TOOL_VIEWS_TOO_LARGE"),
        (_one(**_card(_deep(MAX_DEPTH))), 400, "TOOL_VIEWS_TOO_LARGE"),
        (
            _set(*[_view(f"V{i}", is_default=i == 0) for i in range(MAX_VIEWS + 1)]),
            400,
            "TOOL_VIEWS_LIMIT_REACHED",
        ),
    ],
    ids=[
        "unknown part",
        "unknown field",
        "a property by name",
        "a plug-in field outside the key's characters",
        "a page's part on a card",
        "a column the table cannot draw",
        "a sort by a property",
        "a sort the list cannot order by",
        "a date alone on a page",
        "a property alone on a page",
        "a card on a page",
        "a plug-in field by name",
        "a plug-in part with no part",
        "too many of one plug-in's parts",
        "unknown key",
        "unknown filter value",
        "no default",
        "two defaults",
        "duplicate slug",
        "too many nodes",
        "too deep",
        "too many views",
    ],
)
async def test_a_set_is_refused_unless_every_part_is_one_we_draw(
    client: AsyncClient, acting_user, payload, status: int, detail: str | None
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )

    response = await client.put(
        a.g("/views/"), params=_project(a), json=payload, headers=a.headers
    )

    assert response.status_code == status, response.text
    if detail is not None:
        assert response.json()["detail"] == detail


async def test_a_view_at_the_limits_is_kept(client: AsyncClient, acting_user):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    # The card, a branch to the deepest part, and the rest beside it, among
    # them as many of each of two plug-ins' parts as one plug-in may place.
    parts = [_plugin_part(plugin) for plugin in (3, 4) for _ in range(MAX_PLUGIN_PARTS)]
    card = _card(
        _deep(MAX_DEPTH - 1),
        *parts,
        *[_FIELD] * (MAX_NODES - MAX_DEPTH - len(parts)),
    )

    response = await client.put(
        a.g("/views/"), params=_project(a), json=_one(**card), headers=a.headers
    )
    most = await client.put(
        a.g("/views/"),
        params=_project(a),
        json=_set(*[_view(f"V{i}", is_default=i == 0) for i in range(MAX_VIEWS)]),
        headers=a.headers,
    )

    assert response.status_code == 200, response.text
    assert most.status_code == 200, most.text


async def test_purging_a_project_takes_its_views(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await client.put(a.g("/views/"), params=_project(a), json=_TWO, headers=a.headers)

    trashed = await client.delete(a.g(f"/projects/{a.project.id}"), headers=a.headers)
    assert trashed.status_code == 204, trashed.text
    purged = await client.delete(
        a.g(f"/trash/project/{a.project.id}/purge"), headers=a.headers
    )

    assert purged.status_code == 204, purged.text
    await route_session_to_guild(session, a.guild.id)
    assert (await session.exec(select(ToolView.id))).all() == []


async def test_a_shared_page_is_configured_by_the_initiatives_managers(
    client: AsyncClient, acting_user, reading_as
):
    manager = await acting_user(guild_role=CommunityRole.member, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=manager.guild,
        initiative=manager.initiative,
        initiative_role="member",
    )
    params = {"tool": "calendar", "initiative_id": manager.initiative.id}

    async def can_configure(actor: Any) -> bool:
        response = await client.get(
            actor.g("/views/"), params=params, headers=actor.headers
        )
        assert response.status_code == 200, response.text
        assert [view["slug"] for view in response.json()["views"]] == ["calendar"]
        return response.json()["can_configure"]

    assert (await can_configure(manager), await can_configure(member)) == (True, False)
    refused = await client.put(
        member.g("/views/"), params=params, json=_TWO, headers=member.headers
    )
    assert refused.json()["detail"] == "INITIATIVE_MANAGER_REQUIRED"
    # The calendar draws its own layout alone.
    wrong = await client.put(
        manager.g("/views/"), params=params, json=_TWO, headers=manager.headers
    )
    assert wrong.json()["detail"] == "TOOL_VIEWS_LAYOUT_NOT_ALLOWED"
    # Its event page is saved with its view.
    saved = await client.put(
        manager.g("/views/"), params=params, json=_EVENT_PAGE, headers=manager.headers
    )
    assert saved.status_code == 200, saved.text
    assert [view["slug"] for view in saved.json()["views"]] == ["calendar"]
    (layout,) = saved.json()["item_layouts"]
    assert layout["item_kind"] == "calendar_event"
    assert [part["type"] for part in layout["definition"]["side"]] == [
        "rsvp",
        "section",
    ]

    def row() -> ToolView:
        return ToolView(
            initiative_id=manager.initiative.id,
            tool="calendar",
            kind="view",
            name="Week",
            slug="week",
            definition={},
        )

    writer = await reading_as(manager.user.id, manager.guild.id)
    writer.add(row())
    await writer.commit()
    outsider = await reading_as(member.user.id, member.guild.id)
    outsider.add(row())
    with pytest.raises(DBAPIError):
        await outsider.commit()


def _page(item_kind: str, *side: dict[str, Any]) -> dict[str, Any]:
    return {
        **_set(_view("Calendar", "calendar", slug="calendar", is_default=True)),
        "item_layouts": [{"item_kind": item_kind, "definition": {"side": list(side)}}],
    }


_EVENT_PAGE = _page(
    "calendar_event",
    {"type": "rsvp"},
    {
        "type": "section",
        "children": [
            {"type": "dates"},
            {"type": "field", "props": {"field": "location"}},
        ],
    },
)


@pytest.mark.parametrize(
    ("target", "payload"),
    [
        ("calendar", _page("calendar_event", {"type": "status"})),
        (
            "calendar",
            _page(
                "calendar_event",
                {"type": "section", "children": [_field("checklist")]},
            ),
        ),
        ("calendar", _page("calendar_event", _plugin_part(3))),
        ("calendar", _page("calendar_event", _field("plugin:3:ci.state"))),
        ("calendar", _page("task")),
        ("project", {**_page("task", {"type": "rsvp"}), **_one()}),
        ("project", {**_page("task", _field("location")), **_one()}),
        ("project", {**_page("calendar_event"), **_one()}),
    ],
    ids=[
        "a task's part on an event's page",
        "a task's field on an event's page",
        "a plug-in's part on an event's page",
        "a plug-in's field on an event's page",
        "a task's page on the calendar",
        "an event's part on a task's page",
        "an event's field on a task's page",
        "an event's page on a project",
    ],
)
async def test_an_items_page_draws_only_what_its_kind_has(
    client: AsyncClient, acting_user, target: str, payload: dict[str, Any]
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    params = (
        _project(a)
        if target == "project"
        else {"tool": "calendar", "initiative_id": a.initiative.id}
    )

    response = await client.put(
        a.g("/views/"), params=params, json=payload, headers=a.headers
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "TOOL_VIEWS_LAYOUT_NOT_ALLOWED"


@pytest.mark.parametrize(
    "params",
    [
        {"tool": "project"},
        {"tool": "calendar", "tool_id": 1},
        {"tool": "wiki", "tool_id": 1},
    ],
    ids=["no instance", "an instance of a shared page", "a tool with no views"],
)
async def test_a_target_must_name_what_its_tool_takes(
    client: AsyncClient, acting_user, params: dict[str, Any]
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)

    response = await client.get(a.g("/views/"), params=params, headers=a.headers)

    assert response.status_code == 400
    assert response.json()["detail"] == "TOOL_VIEWS_TARGET_INVALID"
